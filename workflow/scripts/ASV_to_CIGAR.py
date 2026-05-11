#!/usr/bin/env python
"""Align ASVs to target amplicon reference and report variants as CIGAR strings
"""
import argparse
import sys
import os
import subprocess
import re

from Bio import SeqIO, AlignIO

# default location of amplicon sequences and DUST mask info for the gt-seq panel
AMPLICON_DATABASE="/gsap/garage-protistvector/ampseq_data/AmpSeQC/amplicons_noprimers.fasta"

verbose = False # set to true to report more messages

# parse amplicon dust mask info
def parse_dustmasker(mask_info):
    """Parse DUST accloc format mask info"""
    if not mask_info:
        return
    mask = {}
    with open(mask_info) as f:
        for line in f:
            line = line.strip().split("\t")
            gene = line[0].split(":")[0][1:]
            if gene not in mask:
                mask[gene] = set()
            start = int(line[1])+1 # mask info is 0-based, but we want 1-based
            end = int(line[2])+2 # +1 for 1-based and +1 to include last pos in range
            mask[gene].update(list(range(start, end))) # add all pos in between start and end
    if not mask:
        print("ERROR: No mask data loaded! Is the file the correct format?", file=sys.stderr)
        sys.exit(1)
    return mask


# parse amplicon database
def parse_amp_db(fasta_file=AMPLICON_DATABASE):
    """Load sequences from fasta file of amplicons"""
    amplicons = {}
    for seq in SeqIO.parse(fasta_file, "fasta"):
        amplicons[seq.id] = seq
    return amplicons


# parse asv to amplicon table
def parse_asv_table(file, min_reads=0, min_samples=0, max_snv_dist=-1, max_indel_dist=-1, include_failed=False, exclude_bimeras=False):
    """Parse DADA2 ASV table format"""
    bins = {}
    with open(file) as f:
        f.readline()
        for line in f:
            line = line.strip().split("\t")
            # total reads
            if int(line[2]) < min_reads: 
                continue # skip if too few total reads
            # total samples
            if int(line[3]) < min_samples: 
                continue # skip if in too few samples
            # minimum SNV distance
            if max_snv_dist >= 0 and int(line[6]) > max_snv_dist:
                continue # skip if snv distance > threshold
            # minimum indel distance
            if max_indel_dist >= 0 and int(line[7]) > max_indel_dist:
                continue # skip if indel distance > threshold
            # check for failing the snv_filter and indel_filter
            if not include_failed and (line[-3] == "FAIL" or line[-2] == "FAIL"):
                continue # failed post-DADA2 filters
            # check for dada2 calling asv a bimera
            if exclude_bimeras and line[-1].strip().upper() == "TRUE":
                continue # skip if dada2 called bimera
            ASV = line[0] # (e.g. ASV123)
            amplicon = line[5] # target gene/amplicon
            if amplicon not in bins:
                bins[amplicon] = []
            bins[amplicon].append(ASV)
    return bins # bins is dict of amplicon -> list of ASVs assigned to amplicon


# parse ASV fasta file
def get_asv_seqs(file):
    """Load ASV sequences from fasta file"""
    return {seq.id: seq for seq in SeqIO.parse(file, "fasta")}


# write amplicon fasta files
def wrte_amplicon_fastas(asvs, bins, amplicons, outdir="ASVs"):
    """Write one fasta file per amplicon, containing reference sequence and assigned ASVs"""
    if not os.path.isdir(outdir):
        os.mkdir(outdir)
    
    for amplicon in bins:
        if amplicon not in amplicons:
            print(f"WARNING: {amplicon} target not found in amplicon sequence database", file=sys.stderr)
            continue
        with open(os.path.join(outdir, f"{amplicon}.fasta"), "w") as w:
            SeqIO.write(amplicons[amplicon], w, "fasta")
            SeqIO.write([asvs[asv] for asv in bins[amplicon]], w, "fasta")


def muscle_version():
    """Return MUSCLE version text, if available."""
    try:
        result = subprocess.run(["muscle", "-version"], capture_output=True, text=True)
    except FileNotFoundError:
        print("ERROR: MUSCLE executable not found in PATH", file=sys.stderr)
        sys.exit(1)
    return (result.stdout + result.stderr).strip()


def muscle_command(fasta, msa, version_text):
    """Build a MUSCLE command compatible with installed major versions."""
    if re.search(r"\b(v?5(\.|\b)|MUSCLE\s+v?5)", version_text, flags=re.IGNORECASE):
        return ["muscle", "-align", fasta, "-output", msa]
    return ["muscle", "-in", fasta, "-out", msa]


# run muscle for each amplicon
def run_muscle(bins, outdir="ASVs"):
    """Iterate through amplicons, aligning each one with MUSCLE."""
    version_text = muscle_version()
    if version_text:
        print(f"INFO: {version_text.splitlines()[0]}", file=sys.stderr)
    for amplicon in bins:
        fasta = os.path.join(outdir, f"{amplicon}.fasta")
        if not os.path.isfile(fasta):
            print(f"ERROR: Could not find {fasta}", file=sys.stderr)
            continue
        msa = os.path.join(outdir, f"{amplicon}.msa")
        cmd = muscle_command(fasta, msa, version_text)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"ERROR: MUSCLE failed for {amplicon}: {' '.join(cmd)}", file=sys.stderr)
            if result.stdout:
                print(result.stdout, file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            sys.exit(result.returncode)
        if not os.path.isfile(msa) or os.path.getsize(msa) == 0:
            print(f"ERROR: MUSCLE completed but did not create {msa}", file=sys.stderr)
            if result.stdout:
                print(result.stdout, file=sys.stderr)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            sys.exit(1)


# get coords of homopolymer runs
def _get_homopolymer_runs(seq, min_length=5):
    """Detect and report homopolymer runs of minimum length"""
    runs = set()
    prev = None
    run = 1
    start = None
    last_non_gap = None
    for i in range(len(seq)):
        if seq[i] == "-":
            continue
        if seq[i] == prev:
            if not start:
                if i > 1 and seq[i-2] == '-':
                    # gap at start of run
                    j = i - 2
                    while j >= 0:
                        if seq[j] != "-":
                            start = j+1 # start is the start of the gap
                            break
                        j -= 1
                    else:
                        start = 0
                else:
                    start = last_non_gap
            run += 1
        else:
            if run >= min_length:
                runs.update(list(range(start, i)))
            run = 1
            start = None
        prev = seq[i]
        last_non_gap = i
    
    return runs


# parse muscle alignment
def parse_alignment(alignment, mask={}, min_homopolymer_length=5, amplicon=None):
    """Parse amplicon alignment file, converting ASV to CIGAR string"""
    aln = AlignIO.read(alignment, "fasta")
    # sort such that amplicon reference is first in alignment
    aln.sort(key = lambda record: (record.id != amplicon, record.id))
    anchor = aln[0]
    if anchor.id != amplicon:
        print(f"ERROR: No anchor gene for {alignment}", file=sys.stderr)
        # don't parse if amplicon reference not in alignment (this shouldn't happen)
        return

    if min_homopolymer_length > 1:
        # detect homopolymer runs in reference sequence
        homopolymer_runs = _get_homopolymer_runs(aln[0], min_length=min_homopolymer_length)

    if len(anchor.seq.lstrip("-")) != aln.get_alignment_length():
        print(f"WARNING: {os.path.basename(alignment)} extends beyond 5' end of reference sequence!", file=sys.stderr)
    elif len(anchor.seq.rstrip("-")) != aln.get_alignment_length():
        print(f"WARNING: {os.path.basename(alignment)} extends beyond 3' end of reference sequence!", file=sys.stderr)

    masked = mask.get(aln[0].id, None)

    asv_to_cigar = {}
    for seq in aln[1:]:
        pos = 1 # start at position 1 in anchor sequence
        cigar = ""  # cigar string to output, start empty
        indel = False # indicate alignment column in an indel
        masking = False # indicate alignment column is being masked
        for i in range(aln.get_alignment_length()):
            # if anchor pos masked, or next base in anchor is masked and anchor position is a gap
            if masked and (pos in masked or (pos+1 in masked and anchor[i] == '-')):
                if verbose and seq.id == aln[1].id:
                    if not masking:
                        print(f"INFO: Skipping masked positions starting at {pos} in {os.path.basename(alignment)}", file=sys.stderr)
                        if anchor[i] == '-':
                            print(f"INFO: Gap in alignment at start of masked region!", file=sys.stderr)
                        masking = True
                    elif pos not in masked:
                        print(f"INFO: Ending masked positions at {pos-1} in {os.path.basename(alignment)}", file=sys.stderr)
                        masking = False
            elif min_homopolymer_length > 1 and i in homopolymer_runs:
                if verbose and seq.id == aln[1].id:
                    if i and i-1 not in homopolymer_runs:
                        print(f"INFO: Skipping homopolymer run (poly-{anchor[i]}) beginning at position {pos} in {os.path.basename(alignment)}", file=sys.stderr)
                    elif i+1 not in homopolymer_runs:
                        print(f"INFO: End of homopolymer run (poly-{anchor[i]}) at position {pos} in {os.path.basename(alignment)}", file=sys.stderr)
            elif seq[i] != anchor[i]:
                if anchor[i] == "-":
                    if not indel:
                        indel = True
                        cigar += f"{pos}I="
                        if i:
                            for j in range(1,len(anchor)-i):
                                if anchor[i-j] != "-":
                                    cigar += anchor[i-j]
                                    break
                    cigar += seq[i]
                elif seq[i] == "-":
                    if not indel:
                        indel = True
                        cigar += f"{pos}D="
                    cigar += f"{anchor[i]}"
                else:
                    cigar += f"{pos}{seq[i]}"
                    indel = False
            else:
                indel = False
            if anchor[i] != '-':
                pos += 1

        if not cigar:
            cigar = "."
        asv_to_cigar[seq.id] = cigar
    return asv_to_cigar


# get variants per amplicon per position
def parse_alignments(bins, mask={}, min_homopolymer_length=5, outdir="ASVs"):
    """Parse multi-sequence alignment fasta file from MUSCLE"""
    cigars = {}
    for amplicon in sorted(bins):
        msa = os.path.join(outdir, f"{amplicon}.msa")
        if not os.path.isfile(msa):
            print(f"ERROR: Could not find {msa}", file=sys.stderr)
            continue
        # store CIGAR strings per amplicon in dict
        cigars[amplicon] = parse_alignment(msa, mask=mask, min_homopolymer_length=min_homopolymer_length, amplicon=amplicon)
    
    return cigars


# write table of asv -> amplicon/cigar
def write_cigar_strings(cigars, out):
    """Write conversion table from ASV to CIGAR string"""
    number = re.compile(r"\d+")
    with open(out, 'w') as w:
        # write tab file with ASV, amplicon target, and CIGAR string
        w.write("ASV\tAmplicon\tCIGAR\n")
        for amplicon in sorted(cigars):
            # sort on ASV number
            for ASV in sorted(cigars[amplicon], key = lambda x: int(number.search(x).group())):
                w.write(f"{ASV}\t{amplicon}\t{cigars[amplicon][ASV]}\n")


def build_sequence_to_asv(asvs):
    """Map ASV nucleotide sequences back to their explicit ASV IDs."""
    sequence_to_asv = {}
    duplicate_sequences = set()
    for asv_id, record in asvs.items():
        sequence = str(record.seq).upper()
        if sequence in sequence_to_asv:
            duplicate_sequences.add(sequence)
        sequence_to_asv[sequence] = asv_id
    if duplicate_sequences:
        print(
            f"ERROR: Duplicate ASV sequences found in ASV FASTA: {len(duplicate_sequences)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return sequence_to_asv


def resolve_seqtab_asv(column_name, asv_to_cigar, sequence_to_asv):
    """Resolve a seqtab column to an explicit ASV ID.

    The historical seqtab uses nucleotide sequences as columns, while the
    post-processed ASV table and FASTA use ASV1, ASV2, ... IDs. Prefer explicit
    IDs if present, otherwise map by nucleotide sequence.
    """
    if column_name in asv_to_cigar:
        return column_name
    return sequence_to_asv.get(column_name.upper())


def convert_seqtab(file, cigars, out, asvs=None):
    """Parse seqtab file, converting ASVs to CIGAR strings."""
    # get dict of ASVs -> amplicon/CIGAR
    asv_to_cigar = {}
    variants = set()
    for amplicon in sorted(cigars):
        for ASV in sorted(cigars[amplicon]):
            variant = f"{amplicon},{cigars[amplicon][ASV]}"
            asv_to_cigar[ASV] = variant
            variants.add(variant)
    
    if not variants:
        print("ERROR: No haplotypes to convert!", file=sys.stderr)
        return

    sequence_to_asv = build_sequence_to_asv(asvs) if asvs is not None else {}
    total_reads = {}
    # parse seqtab file
    with open(file) as f:
        seqtab = {}
        header = f.readline().rstrip("\n").split("\t")
        if len(header) < 2:
            print(f"ERROR: Seqtab header has no ASV columns: {file}", file=sys.stderr)
            return
        seqtab_columns = header[1:]
        resolved_asvs = [
            resolve_seqtab_asv(column, asv_to_cigar, sequence_to_asv)
            for column in seqtab_columns
        ]
        contract_failures = [
            column for column, asv in zip(seqtab_columns, resolved_asvs)
            if asv is None and column not in asv_to_cigar
        ]
        if contract_failures:
            print(
                "ERROR: Seqtab columns could not be mapped to ASV IDs from the ASV FASTA. "
                f"First unmapped column: {contract_failures[0][:80]}",
                file=sys.stderr,
            )
            return

        for line in f:
            line = line.strip().split("\t")
            if len(line) != len(header):
                print(
                    f"ERROR: Seqtab row for {line[0] if line else '<empty>'} has "
                    f"{len(line)} fields; expected {len(header)}",
                    file=sys.stderr,
                )
                return
            sample = line[0]
            seqtab[sample] = {}
            for asv, count in zip(resolved_asvs, line[1:]):
                variant = asv_to_cigar.get(asv)
                if not variant:
                    continue # ASV was filtered out
                # sum ASVs per sample that are the same variant
                count = int(count)
                if variant not in total_reads:
                    total_reads[variant] = 0
                total_reads[variant] += count
                if variant not in seqtab[sample]:
                    seqtab[sample][variant] = 0
                seqtab[sample][variant] += count
        
        if not seqtab:
            print("ERROR: No seqtab data to write!", file=sys.stderr)
            return

        # write output file (sort variants first)
        variants = sorted(list(variants), key=lambda variant: total_reads.get(variant, 0), reverse=True)
        with open(out, "w") as w:
            # write header
            w.write("sample\t" + "\t".join(variants) + "\n")
            # write one sample per line
            for sample in sorted(seqtab):
                w.write(f"{sample}\t" + "\t".join([f"{seqtab[sample].get(variant, 0)}" for variant in variants]) + "\n")
        
            return True


def build_parser():
    parser = argparse.ArgumentParser(usage="%(prog)s [options] fasta table alignments out",
                                     description="Convert ASVs from DADA2 pipeline to pseudo-CIGAR strings.",
                                     epilog="(C)2021 Broad Institute")
    parser.add_argument("fasta", help="Fasta file of ASV sequences from DADA2 pipeline")
    parser.add_argument("table", help="ASV table from DADA2 pipeline")
    parser.add_argument("seqtab", help="DADA2 seqtab tsv file")
    parser.add_argument("out", help="Output seqtab tsv file with amplicon/variant counts")
    parser.add_argument("--asv_to_cigar", help="Output file for ASV -> CIGAR string table")
    parser.add_argument("-a", "--alignments", default="alignments", help="Directory to store ASV alignment files (default: alignments)")
    parser.add_argument("-p", "--polyN", type=int, default=5, help="Mask homopolymer runs length >= polyN (default: 5; disabled < 2)")
    parser.add_argument("-r", "--min_reads", type=int, default=0, help="Minimum total reads to include ASV (default: 0, disabled)")
    parser.add_argument("-n", "--min_samples", type=int, default=0, help="Minimum samples to include ASV (default: 0, disabled)")
    parser.add_argument("-f", "--include_failed", action="store_true", default=False, help="INCLUDE ASVs that failed post-DADA2 filters (default: False)")
    parser.add_argument("-b", "--exclude_bimeras", action="store_true", default=False, help="EXCLUDE ASVs that DADA2 flagged as bimeras (default: False)")
    parser.add_argument("-s", "--max_snv_dist", type=int, default=-1, help="Maximum SNV distance to include ASV (default: -1, disabled)")
    parser.add_argument("-i", "--max_indel_dist", type=int, default=-1, help="Maximum indel distance to include ASV (default: -1, disabled)")
    parser.add_argument("-d", "--amp_db", default=AMPLICON_DATABASE, help=f"Amplicon sequence fasta file (default: {AMPLICON_DATABASE})")
    parser.add_argument("-m", "--amp_mask", default=None, help=f"Amplicon low complexity mask info (default: None, disabled)")
    parser.add_argument("-v", "--verbose", default=False, action='store_true', help="Increase verbosity")
    return parser


def main():
    global verbose
    parser = build_parser()
    args = parser.parse_args()

    if args.verbose:
        verbose = True

    print(f"INFO: Loading {args.amp_db}", file=sys.stderr)
    amplicons = parse_amp_db(args.amp_db)
    if not amplicons:
        print(f"ERROR: No amplicons in {args.amp_db}", file=sys.stderr)
        sys.exit(1)

    if args.amp_mask:
        print(f"INFO: Loading {args.amp_mask}", file=sys.stderr)
        mask = parse_dustmasker(args.amp_mask)
    else:
        print(f"INFO: No mask data specified.", file=sys.stderr)
        mask = {}

    print(f"INFO: Loading {args.fasta}")
    asvs = get_asv_seqs(args.fasta)
    if not asvs:
        print(f"ERROR: No ASV sequences in {args.fasta}", file=sys.stderr)
        sys.exit(1)

    print(f"INFO: Parsing {args.table} with total reads >= {args.min_reads}, samples >= {args.min_samples}, snv_dist <= {args.max_snv_dist}, indel_dist <= {args.max_indel_dist}", file=sys.stderr)

    if args.include_failed:
        print("WARNING: Including ASVs that failed post-DADA2 filters! This is not recommended.", file=sys.stderr)
    else:
        print("INFO: Excluding ASVs that failed post-DADA2 filters.", file=sys.stderr)

    if args.exclude_bimeras:
        print("INFO: Excluding ASVs that DADA2 marked as bimeras.", file=sys.stderr)

    bins = parse_asv_table(args.table, min_reads=args.min_reads, min_samples=args.min_samples, max_snv_dist=args.max_snv_dist, max_indel_dist=args.max_indel_dist, include_failed=args.include_failed, exclude_bimeras=args.exclude_bimeras)
    if not bins:
        print(f"ERROR: No useable data in {args.table}", file=sys.stderr)
        sys.exit(1)

    outdir = args.alignments
    print(f"INFO: Writing amplicon fasta files to {outdir}", file=sys.stderr)
    if not os.path.isdir(outdir):
        os.mkdir(outdir)
    wrte_amplicon_fastas(asvs, bins, amplicons, outdir=outdir)

    print("INFO: Running MUSCLE aligner on amplicon fasta files. Please wait...", file=sys.stderr)
    run_muscle(bins, outdir=outdir)

    print("INFO: Parsing alignments to CIGAR strings", file=sys.stderr)
    cigars = parse_alignments(bins, mask=mask, min_homopolymer_length=args.polyN, outdir=outdir)
    if not cigars:
        print("ERROR: could not determine CIGAR strings", file=sys.stderr)
        sys.exit(1)

    if args.asv_to_cigar:
        write_cigar_strings(cigars, args.asv_to_cigar)
        print(f"INFO: Wrote ASV->CIGAR table to {args.asv_to_cigar}", file=sys.stderr)

    print(f"INFO: Converting DADA2 seqtab file {args.seqtab} to {args.out}", file=sys.stderr)
    if convert_seqtab(args.seqtab, cigars, args.out, asvs=asvs):
        print("INFO: Completed successfully!", file=sys.stderr)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()


#!/bin/r env

library(seqinr)
library(data.table)
library(argparse)
library(Biostrings)
library(parallel)
library(doMC)

get_alignment_fun <- function(fun_name) {
  for (namespace in c("pwalign", "Biostrings", "BiocGenerics")) {
    if (requireNamespace(namespace, quietly = TRUE) &&
        exists(fun_name, envir = asNamespace(namespace), inherits = FALSE)) {
      return(get(fun_name, envir = asNamespace(namespace)))
    }
  }
  stop(paste("Alignment function not found:", fun_name))
}

pw_nucleotideSubstitutionMatrix <- get_alignment_fun("nucleotideSubstitutionMatrix")
pw_pairwiseAlignment <- get_alignment_fun("pairwiseAlignment")
pw_consensusString <- get_alignment_fun("consensusString")
pw_compareStrings <- get_alignment_fun("compareStrings")

parser <- ArgumentParser()
parser$add_argument("-s", "--seqtab", 
                    help="Path to input")
parser$add_argument("-ref", "--reference",
                    help="Path to reference fasta sequences")
parser$add_argument("-o", "--output",
                    help="Path to output for corrected ASV list")

args <- parser$parse_args()
path_to_refseq <- args$reference

if (file.exists(path_to_refseq)) {
  ref <- toupper(sapply(read.fasta(path_to_refseq),c2s))
} else {
  stop("Reference file not found!")
}

if (!is.null(args$seqtab)) {
  seqfile <- args$seqtab
  if (file.exists(seqfile)) {
    seqtab <- as.matrix(fread(seqfile), rownames=1)
  } else {
    stop(paste("ASV sequence table file",seqtab,"not found!"))
  }
} else {
  stop("Sequence table file (--seqtab) is required")
}

sigma <- pw_nucleotideSubstitutionMatrix(match = 2, mismatch = -1, baseOnly = FALSE)
seqs <- as.character(colnames(seqtab))

registerDoMC(detectCores())
df <- foreach(i=1:length(seqs), .combine = "rbind") %dopar% {
  map <- pw_pairwiseAlignment(ref, seqs[i],substitutionMatrix = sigma, gapOpening = -8, gapExtension = -5, scoreOnly = TRUE)
  tar = ref[which.max(map)]
  seq <- strsplit(seqs[i],"NNNNNNNNNN")[[1]]
  if (length(seq) < 2) {
    N <- NA
    correctedASV <- NA
  } else {
    aln <- pw_pairwiseAlignment(seq[1:2], tar, substitutionMatrix = sigma, gapOpening = -8, gapExtension = -5, scoreOnly = FALSE, type = 'overlap')
    con <- pw_compareStrings(pw_consensusString(aln[1]),pw_consensusString(aln[2]))
    overlap <- gregexpr("[[:alpha:]]", con)[[1]]
    has_overlap <- !(length(overlap) == 1 && overlap[1] == -1)
    if (!has_overlap) {
      N = (nchar(seq[1])+nchar(seq[2])) - nchar(tar)
      stkN <- paste0(rep('N',abs(N)),collapse = '')
      correctedASV <- paste0(seq[1],stkN,seq[2])
    } else {
      N = length(overlap)
      correctedASV <- paste0(seq[1],substr(seq[2],(N+1),nchar(seq[2])))
    }
  }
  if (is.na(correctedASV) || nchar(correctedASV) != nchar(tar)) {
    N = NA
    correctedASV = NA
  }
  data.frame(target = names(tar),
             ASV = seqs[i],
             correctedASV = correctedASV,
             overlap = N)
}
write.table(df, file = args$output, sep = "\t", quote = FALSE, row.names = FALSE)
seqfile_corrected <- paste0(dirname(seqfile),"/seqtab_corrected.tsv")
corrected_names <- as.character(df$correctedASV)
valid_corrected <- !is.na(corrected_names) & corrected_names != "NA"
seqtab_corrected <- seqtab[, valid_corrected, drop = FALSE]
colnames(seqtab_corrected) <- corrected_names[valid_corrected]

if (ncol(seqtab_corrected) > 0) {
  seqtab_corrected <- t(rowsum(t(seqtab_corrected), group = colnames(seqtab_corrected)))
  seqtab_corrected <- seqtab_corrected[, order(colnames(seqtab_corrected)), drop = FALSE]
}

write.table(seqtab_corrected, file = seqfile_corrected, sep = "\t", quote = FALSE, row.names = TRUE, col.names = NA)

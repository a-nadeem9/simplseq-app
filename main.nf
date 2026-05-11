#!/usr/bin/env nextflow

process PREFLIGHT {
  tag 'preflight'
  publishDir "${params.outdir}/qc", mode: 'copy', overwrite: true

  input:
  path samples
  path amplicons

  output:
  path 'preflight.tsv', emit: report
  path 'amplicon_geometry.tsv', emit: geometry
  path 'barcode_readiness.tsv', emit: barcode

  script:
  def samples_root = file(params.samples).isAbsolute() ? file(params.samples).parent : "${projectDir}/${file(params.samples).parent}"
  """
  export PATH="/opt/conda/bin:/usr/local/bin:\$PATH"
  export PYTHONPATH="${projectDir}/src:\${PYTHONPATH:-}"
  hash -r
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage prepare_inputs --status started --message "Checking sample sheet"
  python ${projectDir}/workflow/bin/simplseq_nf_helpers.py preflight \
    --samples ${samples} \
    --amplicons ${amplicons} \
    --report preflight.tsv \
    --geometry amplicon_geometry.tsv \
    --barcode barcode_readiness.tsv \
    --inline-barcodes-enabled ${params.inline_barcodes_enabled} \
    --sentinel-locus ${params.sentinel_locus} \
    --samples-root ${samples_root}
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage prepare_inputs --status complete
  """
}

process WRITE_META {
  tag 'meta'
  publishDir "${params.outdir}", mode: 'copy', overwrite: true

  input:
  path samples

  output:
  path 'meta.tsv', emit: meta

  script:
  def samples_root = file(params.samples).isAbsolute() ? file(params.samples).parent : "${projectDir}/${file(params.samples).parent}"
  """
  export PATH="/opt/conda/bin:/usr/local/bin:\$PATH"
  export PYTHONPATH="${projectDir}/src:\${PYTHONPATH:-}"
  hash -r
  python ${projectDir}/workflow/bin/simplseq_nf_helpers.py write-meta --samples ${samples} --out meta.tsv --samples-root ${samples_root}
  """
}

process WRITE_PIPELINE_JSON {
  tag 'pipeline_json'
  publishDir "${params.outdir}/config", mode: 'copy', overwrite: true

  input:
  path meta

  output:
  path 'pipeline_inputs.json', emit: json

  script:
  def dada2_randomize_arg = params.dada2_randomize ? "--dada2-randomize ${params.dada2_randomize}" : ''
  def dada2_multithread_arg = params.dada2_multithread ? "--dada2-multithread ${params.dada2_multithread}" : ''
  def dada2_seed_arg = params.dada2_seed ? "--dada2-seed ${params.dada2_seed}" : ''
  """
  export PATH="/opt/conda/bin:/usr/local/bin:\$PATH"
  export PYTHONPATH="${projectDir}/src:\${PYTHONPATH:-}"
  hash -r
  python ${projectDir}/workflow/bin/simplseq_nf_helpers.py write-pipeline-json \
    --meta ${meta} \
    --out pipeline_inputs.json \
    --pipeline-class ${params.pipeline_class} \
    --max-ee ${params.max_ee} \
    --trim-right ${params.trim_right} \
    --min-len ${params.min_len} \
    --trunc-q ${params.trunc_q} \
    --max-consist ${params.max_consist} \
    --omega-a ${params.omega_a} \
    --just-concatenate ${params.just_concatenate} \
    --save-rdata ${params.save_rdata} \
    ${dada2_randomize_arg} \
    ${dada2_multithread_arg} \
    ${dada2_seed_arg} \
    --primers-fwd ${projectDir}/${params.primers_fwd} \
    --primers-rev ${projectDir}/${params.primers_rev} \
    --overlap-primers-fwd ${projectDir}/${params.overlap_primers_fwd} \
    --overlap-primers-rev ${projectDir}/${params.overlap_primers_rev}
  """
}

process DADA2_PIPELINE {
  tag 'dada2'
  cpus params.dada2_cpus
  memory params.dada2_memory
  time '6h'
  publishDir "${params.outdir}/run_dada2/intermediate/dada2_op", mode: 'copy', overwrite: true, pattern: 'op_ASVBimeras.txt', saveAs: { 'ASVBimeras.txt' }
  publishDir "${params.outdir}/run_dada2/intermediate/dada2_nop", mode: 'copy', overwrite: true, pattern: 'nop_ASVBimeras.txt', saveAs: { 'ASVBimeras.txt' }
  publishDir "${params.outdir}/run_dada2/intermediate/dada2_nop", mode: 'copy', overwrite: true, pattern: 'correctedASV.txt'
  publishDir "${params.outdir}/logs", mode: 'copy', overwrite: true, pattern: 'dada2_pipeline.log'

  input:
  path json
  path meta
  path reference
  path overlap_fwd
  path overlap_rev

  output:
  path 'seqtab_iseq.tsv', emit: seqtab
  path 'op_ASVBimeras.txt', emit: op_bimera
  path 'nop_ASVBimeras.txt', emit: nop_bimera
  path 'correctedASV.txt', emit: corrected_asv
  path 'dada2_pipeline.log', emit: log

  script:
  """
  export PATH="/opt/conda/bin:/usr/local/bin:\$PATH"
  export PYTHONPATH="${projectDir}/src:\${PYTHONPATH:-}"
  hash -r
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage dada2 --status started --message "Running DADA2"
  {
    echo "[SIMPLseq/Nextflow] \$(date) starting DADA2/AmpliconPipeline"
    python ${projectDir}/workflow/scripts/AmpliconPipeline.py \
      --json ${json} \
      --iseq \
      --reference ${reference} \
      --overlap_pr1 ${overlap_fwd} \
      --overlap_pr2 ${overlap_rev}
    echo "[SIMPLseq/Nextflow] \$(date) finished DADA2/AmpliconPipeline"
  } 2>&1 | tee dada2_pipeline.log

  cp run_dada2/seqtab_iseq.tsv seqtab_iseq.tsv
  cp run_dada2/dada2_op/ASVBimeras.txt op_ASVBimeras.txt
  cp run_dada2/dada2_nop/ASVBimeras.txt nop_ASVBimeras.txt
  cp run_dada2/dada2_nop/correctedASV.txt correctedASV.txt
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage dada2 --status complete
  """
}

process PREPARE_STAGE2 {
  tag 'prepare_stage2'
  publishDir "${params.outdir}/run_dada2/intermediate", mode: 'copy', overwrite: true, pattern: 'ASVBimeras_strict.txt'

  input:
  path seqtab
  path op_bimera
  path nop_bimera
  path corrected_asv

  output:
  path 'seqtab_iseq_strict_fixed.tsv', emit: strict_seqtab
  path 'ASVBimeras_strict.txt', emit: strict_bimera

  script:
  """
  export PATH="/opt/conda/bin:/usr/local/bin:\$PATH"
  export PYTHONPATH="${projectDir}/src:\${PYTHONPATH:-}"
  hash -r
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage prepare_stage2 --status started --message "Cleaning ASV table"
  python ${projectDir}/workflow/bin/simplseq_nf_helpers.py prepare-stage2 \
    --seqtab ${seqtab} \
    --op-bimera ${op_bimera} \
    --nop-bimera ${nop_bimera} \
    --corrected-asv ${corrected_asv} \
    --strict-seqtab seqtab_iseq_strict_fixed.tsv \
    --strict-bimera ASVBimeras_strict.txt \
    --strict-min-asv-length ${params.strict_min_asv_length}
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage prepare_stage2 --status complete
  """
}

process POSTPROCESS_DADA2 {
  tag 'postprocess'
  cpus params.postprocess_cpus
  memory params.postprocess_memory
  time '4h'
  publishDir "${params.outdir}/run_dada2/intermediate", mode: 'copy', overwrite: true, pattern: 'ASVSeqs.fasta'
  publishDir "${params.outdir}/logs", mode: 'copy', overwrite: true, pattern: 'postprocess_dada2.log'

  input:
  path seqtab
  path bimera
  path reference
  path snv_filters

  output:
  path 'ASV_mapped_table.tsv', emit: mapped
  path 'ASVSeqs.fasta', emit: fasta
  path 'postprocess_dada2.log', emit: log

  script:
  """
  export PATH="/opt/conda/bin:/usr/local/bin:\$PATH"
  export PYTHONPATH="${projectDir}/src:\${PYTHONPATH:-}"
  hash -r
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage asv_mapping --status started --message "Mapping ASVs"
  {
    echo "[SIMPLseq/Nextflow] \$(date) starting postprocess_dada2"
    Rscript ${projectDir}/workflow/scripts/postProc_dada2.R \
      -s ${seqtab} \
      -ref ${reference} \
      -b ${bimera} \
      -o ASV_mapped_table.tsv \
      --fasta \
      --snv_filter ${snv_filters} \
    --indel_filter ${params.indel_filter}
    echo "[SIMPLseq/Nextflow] \$(date) finished postprocess_dada2"
  } 2>&1 | tee postprocess_dada2.log
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage asv_mapping --status complete
  """
}

process PREPARE_STAGE3 {
  tag 'prepare_stage3'
  publishDir "${params.outdir}/run_dada2", mode: 'copy', overwrite: true

  input:
  path mapped
  path seqtab

  output:
  path 'ASV_mapped_table.tsv', emit: filtered_mapped
  path 'seqtab_iseq.tsv', emit: fixed_seqtab

  script:
  """
  export PATH="/opt/conda/bin:/usr/local/bin:\$PATH"
  export PYTHONPATH="${projectDir}/src:\${PYTHONPATH:-}"
  hash -r
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage prepare_stage3 --status started --message "Preparing CIGAR inputs"
  python ${projectDir}/workflow/bin/simplseq_nf_helpers.py prepare-stage3 \
    --mapped ${mapped} \
    --seqtab ${seqtab} \
    --filtered-mapped ASV_mapped_table.tsv \
    --fixed-seqtab seqtab_iseq.tsv
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage prepare_stage3 --status complete
  """
}

process CHECK_CIGAR_INPUTS {
  tag 'check_cigar_inputs'
  publishDir "${params.outdir}/qc", mode: 'copy', overwrite: true

  input:
  path table

  output:
  path 'cigar_input_summary.tsv', emit: summary

  script:
  def bimera_flag = params.cigar_exclude_bimeras ? '--exclude-bimeras' : ''
  """
  export PATH="/opt/conda/bin:/usr/local/bin:\$PATH"
  export PYTHONPATH="${projectDir}/src:\${PYTHONPATH:-}"
  hash -r
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage cigar_check --status started --message "Checking CIGAR inputs"
  python ${projectDir}/workflow/bin/simplseq_nf_helpers.py check-cigar-inputs \
    --table ${table} \
    --summary cigar_input_summary.tsv \
    --min-reads ${params.cigar_min_total_reads} \
    --min-samples ${params.cigar_min_samples} \
    ${bimera_flag}
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage cigar_check --status complete
  """
}

process CIGAR_CONVERSION {
  tag 'cigar'
  cpus params.cigar_cpus
  memory params.cigar_memory
  time '1h'
  publishDir "${params.outdir}/run_dada2", mode: 'copy', overwrite: true, pattern: 'seqtab_cigar.tsv'
  publishDir "${params.outdir}/run_dada2", mode: 'copy', overwrite: true, pattern: 'asv_to_cigar.tsv'
  publishDir "${params.outdir}/logs", mode: 'copy', overwrite: true, pattern: 'cigar_conversion.log'

  input:
  path fasta
  path table
  path seqtab
  path reference
  path summary

  output:
  path 'seqtab_cigar.tsv', emit: seqtab_cigar
  path 'asv_to_cigar.tsv', emit: asv_to_cigar
  path 'cigar_conversion.log', emit: log

  script:
  def bimera_flag = params.cigar_exclude_bimeras ? '-b' : ''
  """
  export PATH="/opt/conda/bin:/usr/local/bin:\$PATH"
  export PYTHONPATH="${projectDir}/src:\${PYTHONPATH:-}"
  hash -r
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage asv_to_cigar --status started --message "Converting ASVs to CIGAR"
  {
    echo "[SIMPLseq/Nextflow] \$(date) starting CIGAR conversion"
    python ${projectDir}/workflow/scripts/ASV_to_CIGAR.py \
      ${fasta} \
      ${table} \
      ${seqtab} \
      seqtab_cigar.tsv \
      --asv_to_cigar asv_to_cigar.tsv \
      --amp_db ${reference} \
      --alignments alignments \
      -p ${params.cigar_homopolymer_mask_length} \
      -r ${params.cigar_min_total_reads} \
      -n ${params.cigar_min_samples} \
      ${bimera_flag}
    echo "[SIMPLseq/Nextflow] \$(date) finished CIGAR conversion"
  } 2>&1 | tee cigar_conversion.log
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage asv_to_cigar --status complete
  """
}

process RUN_REPORT {
  tag 'run_report'
  publishDir "${params.outdir}/reports", mode: 'copy', overwrite: true

  input:
  path preflight
  path geometry
  path cigar_summary
  path mapped
  path asv_to_cigar
  path cigar

  output:
  path 'run_summary.html', emit: html

  script:
  """
  export PATH="/opt/conda/bin:/usr/local/bin:\$PATH"
  export PYTHONPATH="${projectDir}/src:\${PYTHONPATH:-}"
  hash -r
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage report --status started --message "Writing report"
  python ${projectDir}/workflow/bin/simplseq_nf_helpers.py make-report \
    --project-name ${params.project_name} \
    --preflight ${preflight} \
    --geometry ${geometry} \
    --cigar-summary ${cigar_summary} \
    --mapped ${mapped} \
    --asv-to-cigar ${asv_to_cigar} \
    --cigar ${cigar} \
    --out run_summary.html
  python -m simplseq.progress emit --file "${params.outdir}/progress.jsonl" --stage report --status complete
  """
}

process BIOLOGICAL_EQUIVALENCE {
  tag 'biological_equivalence'
  publishDir "${params.outdir}/qc", mode: 'copy', overwrite: true

  input:
  val frozen_root
  path seqtab_iseq
  path asv_fasta
  path mapped
  path filtered_mapped
  path asv_to_cigar
  path seqtab_cigar

  output:
  path 'biological_equivalence_report.md', emit: md
  path 'biological_equivalence_report.tsv', emit: tsv
  path 'biological_equivalence.log', emit: log

  script:
  def fail_flag = params.biological_equivalence_fail_on_fail ? 'true' : 'false'
  def frozen_root_arg = frozen_root.toString().startsWith('/') ? frozen_root : "${projectDir}/${frozen_root}"
  """
  export PATH="/opt/conda/bin:/usr/local/bin:\$PATH"
  export PYTHONPATH="${projectDir}/src:\${PYTHONPATH:-}"
  hash -r
  mkdir -p nextflow_equivalence_root/run_dada2
  cp ${seqtab_iseq} nextflow_equivalence_root/run_dada2/seqtab_iseq.tsv
  cp ${asv_fasta} nextflow_equivalence_root/run_dada2/ASVSeqs.fasta
  cp ${mapped} nextflow_equivalence_root/run_dada2/ASV_mapped_table.tsv
  cp ${filtered_mapped} nextflow_equivalence_root/run_dada2/ASV_mapped_table.tsv
  cp ${asv_to_cigar} nextflow_equivalence_root/run_dada2/asv_to_cigar.tsv
  cp ${seqtab_cigar} nextflow_equivalence_root/run_dada2/seqtab_cigar.tsv

  set +e
  python ${projectDir}/workflow/scripts/biological_equivalence_report.py \
    --frozen ${frozen_root_arg} \
    --nextflow nextflow_equivalence_root \
    --out biological_equivalence_report.md \
    --report-thresholds ${params.biological_equivalence_thresholds} \
    > biological_equivalence.log 2>&1
  status=\$?
  set -e

  cat biological_equivalence.log
  if [[ "\$status" -ne 0 && "${fail_flag}" == "true" ]]; then
    exit "\$status"
  fi
  """
}

workflow {
  samples = file(params.samples)
  reference = file(params.amplicons_noprimers)
  snv_filters = file(params.snv_filters)
  overlap_fwd = file(params.overlap_primers_fwd)
  overlap_rev = file(params.overlap_primers_rev)

  preflight = PREFLIGHT(samples, reference)
  meta = WRITE_META(samples)
  pipeline_json = WRITE_PIPELINE_JSON(meta.meta)

  dada2 = DADA2_PIPELINE(pipeline_json.json, meta.meta, reference, overlap_fwd, overlap_rev)
  stage2 = PREPARE_STAGE2(dada2.seqtab, dada2.op_bimera, dada2.nop_bimera, dada2.corrected_asv)
  post = POSTPROCESS_DADA2(stage2.strict_seqtab, stage2.strict_bimera, reference, snv_filters)
  stage3 = PREPARE_STAGE3(post.mapped, stage2.strict_seqtab)
  cigar_check = CHECK_CIGAR_INPUTS(stage3.filtered_mapped)
  cigar = CIGAR_CONVERSION(post.fasta, stage3.filtered_mapped, stage3.fixed_seqtab, reference, cigar_check.summary)
  report = RUN_REPORT(preflight.report, preflight.geometry, cigar_check.summary, stage3.filtered_mapped, cigar.asv_to_cigar, cigar.seqtab_cigar)
  if (params.validation_frozen_results) {
    BIOLOGICAL_EQUIVALENCE(
      params.validation_frozen_results,
      dada2.seqtab,
      post.fasta,
      post.mapped,
      stage3.filtered_mapped,
      cigar.asv_to_cigar,
      cigar.seqtab_cigar
    )
  }
}

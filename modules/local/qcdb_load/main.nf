/*
 * QCDB_LOAD: load one run's QC documents into the qcdb PostgreSQL database.
 *
 * Inputs are only read; the step never writes to the pipeline's result files (the loader
 * opens staged files read-only and writes only qcdb_load.log in the task directory).
 * A failed load fails the task (exit 1 validation, 2 usage, 3 unreadable input). To let the
 * pipeline continue anyway, set in the pipeline config:
 *     process { withName: 'QCDB_LOAD' { errorStrategy = 'ignore' } }
 *
 * Database credentials come from Nextflow secrets, never from params:
 *     nextflow secrets set QCDB_DATABASE_URL 'postgresql://qcdb_loader@db.lab.local:5432/qcdb?sslmode=verify-full&sslrootcert=/certs/qcdb-ca.crt'
 *     nextflow secrets set QCDB_DATABASE_PASSWORD '...'
 *
 * Grouping the per-sample documents by run (the pipeline's meta map has meta.id, meta.run_id,
 * meta.taxid and meta.qc_profile):
 *
 *     ch_docs = QCMETRICS.out.json                      // [ meta, *.metrics.json ]
 *         .mix( QCEVAL.out.json, SAMPLE_REPORT.out.json ) // [ meta, *.qc.json / *.report.json ]
 *         .map { meta, json -> [ meta.run_id, json ] }
 *         .groupTuple()
 *         .map { run_id, files -> [ run_id, files.flatten() ] }
 *         .join( RUN_REPORT.out.json )                    // [ run_id, *.run.json ]
 *         .map { run_id, files, run_json -> [ run_id, files + [ run_json ] ] }
 *
 *     QCDB_LOAD ( ch_docs, ch_samplesheet )
 *
 * task.ext.args can add loader options, e.g. ext.args = { "--run-date ${params.run_date}" }.
 */
process QCDB_LOAD {
    tag "${run_id}"
    label 'process_single'
    container 'qcdb:0.1.0'
    secret 'QCDB_DATABASE_URL'
    secret 'QCDB_DATABASE_PASSWORD'

    input:
    tuple val(run_id), path(docs, stageAs: 'qcdb_in/*')
    path samplesheet, stageAs: 'qcdb_in/samplesheet.csv'

    output:
    tuple val(run_id), path("qcdb_load.log"), emit: log
    path "versions.yml",                      emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    """
    set -o pipefail
    export PGPASSWORD="\$QCDB_DATABASE_PASSWORD"    # read by qcdb; never written to disk
    export QCDB_INVOKED_BY='nextflow:${workflow.runName}:${task.hash}'

    status=0
    qcdb load qcdb_in --run-id '${run_id}' ${args} > qcdb_load.log 2>&1 || status=\$?
    cat qcdb_load.log

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        qcdb: \$(qcdb --version | sed 's/^qcdb //')
    END_VERSIONS
    exit \$status
    """

    stub:
    """
    touch qcdb_load.log
    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        qcdb: \$(qcdb --version | sed 's/^qcdb //')
    END_VERSIONS
    """
}

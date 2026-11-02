-- qcdb initial schema (design: docs/design/01-design.md §2.2 and §13)

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-------------------------------------------------------------------- users (needed by audit)
CREATE TABLE app_user (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username        text NOT NULL UNIQUE,
    password_hash   text NOT NULL,
    role            text NOT NULL CHECK (role IN ('admin', 'bioinformatician', 'viewer')),
    is_active       boolean NOT NULL DEFAULT true,
    failed_logins   integer NOT NULL DEFAULT 0,
    locked_until    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_login_at   timestamptz
);

CREATE TABLE user_session (
    token_hash   char(64) PRIMARY KEY,
    user_id      bigint NOT NULL REFERENCES app_user (id) ON DELETE CASCADE,
    csrf_token   text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL
);
CREATE INDEX user_session_user_idx ON user_session (user_id);

-------------------------------------------------------------------- dictionary
CREATE TABLE metric_dictionary_import (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_name   text NOT NULL,
    sha256      char(64) NOT NULL UNIQUE,
    kind        text NOT NULL CHECK (kind IN ('dictionary', 'labels')),
    lang        text,
    n_entries   integer NOT NULL,
    n_added     integer NOT NULL,
    n_changed   integer NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    imported_by text NOT NULL,
    CHECK ((kind = 'labels') = (lang IS NOT NULL))
);

CREATE TABLE metric_definition (
    key                text PRIMARY KEY,
    tool               text NOT NULL,
    metric             text NOT NULL,
    unit               text NOT NULL,
    value_type         text NOT NULL CHECK (value_type IN ('int', 'float', 'str', 'bool')),
    range_min          numeric,
    range_max          numeric,
    label              text NOT NULL,
    description        text NOT NULL,
    added_in_import_id bigint NOT NULL REFERENCES metric_dictionary_import (id),
    UNIQUE (tool, metric),
    CHECK (key = tool || '.' || metric)
);

CREATE TABLE metric_label (
    metric_key  text NOT NULL REFERENCES metric_definition (key),
    lang        text NOT NULL CHECK (lang ~ '^[a-z]{2}$'),
    label       text NOT NULL,
    description text,
    PRIMARY KEY (metric_key, lang)
);

-------------------------------------------------------------------- people, orders, samples
CREATE TABLE owner (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    full_name  text,
    email      text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    erased_at  timestamptz,
    CHECK ((erased_at IS NULL) = (full_name IS NOT NULL)),
    CHECK (erased_at IS NULL OR email IS NULL)
);

CREATE TABLE sample_order (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_code text NOT NULL UNIQUE,
    owner_id   bigint REFERENCES owner (id),
    meta       jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sample_order_owner_idx ON sample_order (owner_id);
CREATE INDEX sample_order_code_trgm ON sample_order USING gin (order_code gin_trgm_ops);

CREATE TABLE sample_field_definition (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key        text NOT NULL UNIQUE CHECK (key ~ '^[a-z][a-z0-9_]*$'),
    label      text NOT NULL,
    data_type  text NOT NULL CHECK (data_type IN ('text', 'number', 'date', 'choice')),
    choices    text[],
    required   boolean NOT NULL DEFAULT false,
    ordinal    integer NOT NULL,
    is_active  boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((data_type = 'choice') = (choices IS NOT NULL))
);

INSERT INTO sample_field_definition (key, label, data_type, ordinal) VALUES
    ('material_type', 'Rodzaj materiału', 'text', 10),
    ('collection_site', 'Źródło / miejsce pobrania', 'text', 20),
    ('collection_date', 'Data pobrania', 'date', 30),
    ('expected_species', 'Oczekiwany gatunek', 'text', 40);

CREATE TABLE sample (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sample_code text NOT NULL,
    metadata    jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sample_code_idx ON sample (sample_code);
CREATE INDEX sample_metadata_gin ON sample USING gin (metadata jsonb_path_ops);

CREATE TABLE order_sample (
    order_id  bigint NOT NULL REFERENCES sample_order (id),
    sample_id bigint NOT NULL REFERENCES sample (id),
    source    text NOT NULL CHECK (source IN ('ui', 'order_json', 'metadata')),
    linked_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (order_id, sample_id)
);
CREATE INDEX order_sample_sample_idx ON order_sample (sample_id);

-------------------------------------------------------------------- loads and raw documents
CREATE TABLE load_batch (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at   timestamptz NOT NULL,
    finished_at  timestamptz,
    invoked_by   text NOT NULL,
    qcdb_version text NOT NULL,
    source_dir   text NOT NULL,
    options      jsonb NOT NULL,
    counts       jsonb
);

CREATE TABLE source_document (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sha256         char(64) NOT NULL UNIQUE,
    kind           text NOT NULL CHECK (kind IN ('metrics', 'qc', 'report', 'run', 'order')),
    schema_version text NOT NULL,
    file_name      text NOT NULL,
    size_bytes     integer NOT NULL,
    content        jsonb NOT NULL,
    first_batch_id bigint NOT NULL REFERENCES load_batch (id)
);

-------------------------------------------------------------------- runs and results
CREATE TABLE run (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_code        text NOT NULL UNIQUE,
    run_date        date,
    run_date_source text CHECK (run_date_source IN ('cli', 'metadata', 'ui')),
    run_document_id bigint REFERENCES source_document (id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK ((run_date IS NULL) = (run_date_source IS NULL))
);
CREATE INDEX run_code_trgm ON run USING gin (run_code gin_trgm_ops);

CREATE TABLE run_membership (
    run_id         bigint NOT NULL REFERENCES run (id),
    sample_code    text NOT NULL,
    source         text NOT NULL CHECK (source IN ('report', 'run_json', 'samplesheet', 'cli')),
    source_sha256  char(64),
    run_json_entry jsonb,
    PRIMARY KEY (run_id, sample_code, source),
    CHECK ((source = 'cli') = (source_sha256 IS NULL))
);

CREATE TABLE sample_run (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id             bigint NOT NULL REFERENCES run (id),
    sample_code        text NOT NULL,
    sample_id          bigint REFERENCES sample (id),
    current_version_id bigint,
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, sample_code)
);
CREATE INDEX sample_run_sample_idx ON sample_run (sample_id);
CREATE INDEX sample_run_code_trgm ON sample_run USING gin (sample_code gin_trgm_ops);

CREATE TABLE result_version (
    id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sample_run_id            bigint NOT NULL REFERENCES sample_run (id),
    version_no               integer NOT NULL CHECK (version_no >= 1),
    load_batch_id            bigint NOT NULL REFERENCES load_batch (id),
    fingerprint              char(64) NOT NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    has_qc                   boolean NOT NULL,
    has_report               boolean NOT NULL,
    qc_document_id           bigint REFERENCES source_document (id),
    verdict                  text CHECK (verdict IN ('PASS', 'WARN', 'FAIL')),
    evaluator_version        text,
    thresholds_file          text,
    thresholds_sha256        char(64),
    profile                  text,
    read_length_profile      text,
    threshold_species        text,
    threshold_chain          text[],
    expected_taxid           integer,
    context_read_length      numeric,
    depth_basis              text,
    reasons                  text[],
    advisory                 text[],
    notes                    text[],
    unused_inputs            text[],
    qc_inputs                jsonb,
    report_document_id       bigint REFERENCES source_document (id),
    report_run_id            text,
    meta                     jsonb,
    report_generator_version text,
    pipeline                 text,
    pipeline_version         text,
    nextflow_version         text,
    software                 jsonb,
    typing_species           jsonb,
    load_warnings            text[] NOT NULL DEFAULT '{}',
    UNIQUE (sample_run_id, version_no),
    UNIQUE (sample_run_id, fingerprint),
    UNIQUE (id, sample_run_id),
    CHECK (has_qc = (qc_document_id IS NOT NULL)),
    CHECK (has_qc = (verdict IS NOT NULL)),
    CHECK (has_report = (report_document_id IS NOT NULL))
);
CREATE INDEX result_version_sha_idx ON result_version (thresholds_sha256);

-- The current version must belong to the same sample_run (composite FK, NULL = no results).
ALTER TABLE sample_run ADD CONSTRAINT sample_run_current_fk
    FOREIGN KEY (current_version_id, id) REFERENCES result_version (id, sample_run_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE tool_result (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version_id       bigint NOT NULL REFERENCES result_version (id) ON DELETE CASCADE,
    document_id      bigint NOT NULL REFERENCES source_document (id),
    tool             text NOT NULL,
    namespace        text NOT NULL CHECK (namespace IN ('input', 'demux', 'reads', 'composition',
                                                        'species', 'assembly', 'characterisation')),
    status           text NOT NULL CHECK (status IN ('ok', 'empty', 'skipped', 'failed', 'missing')),
    messages         text[],
    tool_version     text NOT NULL,
    database_version text,
    parser_name      text NOT NULL,
    parser_version   text NOT NULL,
    schema_version   text NOT NULL,
    inputs           jsonb,
    data             jsonb,
    UNIQUE (version_id, tool)
);

CREATE TABLE metric_value (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tool_result_id bigint NOT NULL REFERENCES tool_result (id) ON DELETE CASCADE,
    metric_key     text NOT NULL REFERENCES metric_definition (key),
    unit           text NOT NULL,
    value_num      numeric,
    value_text     text,
    value_bool     boolean,
    CHECK (num_nonnulls(value_num, value_text, value_bool) <= 1),
    UNIQUE (tool_result_id, metric_key)
);
CREATE INDEX metric_value_trend_idx ON metric_value (metric_key, tool_result_id) INCLUDE (value_num);

CREATE TABLE qc_check (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version_id bigint NOT NULL REFERENCES result_version (id) ON DELETE CASCADE,
    ordinal    smallint NOT NULL,
    metric     text NOT NULL,
    value_num  numeric,
    value_text text,
    unit       text,
    rule       jsonb NOT NULL,
    required   boolean NOT NULL,
    status     text NOT NULL CHECK (status IN ('PASS', 'WARN', 'FAIL', 'NA')),
    reason     text,
    CHECK (num_nonnulls(value_num, value_text) <= 1),
    CHECK ((status = 'PASS') = (reason IS NULL)),
    CHECK (status <> 'NA' OR (NOT required AND value_num IS NULL AND value_text IS NULL)),
    UNIQUE (version_id, ordinal)
);
CREATE INDEX qc_check_metric_idx ON qc_check (metric);

CREATE TABLE amr_hit (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tool_result_id bigint NOT NULL REFERENCES tool_result (id) ON DELETE CASCADE,
    ordinal        integer NOT NULL,
    symbol         text,
    name           text,
    type           text,
    subtype        text,
    class          text,
    subclass       text,
    method         text,
    pct_identity   numeric,
    pct_coverage   numeric,
    scope          text,
    contig         text,
    start_pos      bigint,
    stop_pos       bigint,
    strand         text,
    accession      text,
    UNIQUE (tool_result_id, ordinal)
);
CREATE INDEX amr_hit_symbol_idx ON amr_hit (symbol);
CREATE INDEX amr_hit_class_idx ON amr_hit (class);

CREATE TABLE species_abundance (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tool_result_id bigint NOT NULL REFERENCES tool_result (id) ON DELETE CASCADE,
    ordinal        integer NOT NULL,
    name           text,
    taxid          integer,
    reads          bigint,
    pct            numeric,
    UNIQUE (tool_result_id, ordinal)
);
CREATE INDEX species_abundance_name_idx ON species_abundance (name, pct);

-------------------------------------------------------------------- audit
CREATE TABLE audit_log (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at   timestamptz NOT NULL DEFAULT now(),
    actor_user_id bigint REFERENCES app_user (id),
    actor_label   text NOT NULL,
    load_batch_id bigint REFERENCES load_batch (id),
    action        text NOT NULL,
    entity_type   text NOT NULL,
    entity_id     text NOT NULL,
    changes       jsonb NOT NULL
);
CREATE INDEX audit_log_entity_idx ON audit_log (entity_type, entity_id, occurred_at);

-------------------------------------------------------------------- sample table (D2, D3)
CREATE MATERIALIZED VIEW sample_run_summary AS
SELECT
    sr.id                         AS sample_run_id,
    sr.run_id,
    r.run_code,
    r.run_date,
    sr.sample_code,
    sr.sample_id,
    rv.id                         AS version_id,
    rv.version_no,
    (SELECT count(*) FROM result_version x WHERE x.sample_run_id = sr.id) AS n_versions,
    (rv.id IS NOT NULL)           AS has_results,
    coalesce(rv.has_qc, false)    AS has_qc,
    coalesce(rv.has_report, false) AS has_report,
    rv.verdict,
    rv.profile,
    rv.read_length_profile,
    rv.thresholds_sha256,
    CASE WHEN rv.typing_species -> 'available' = 'true'::jsonb
         THEN rv.typing_species ->> 'name' END AS species,
    m.mlst_st,
    coalesce(m.seqsero2_serotype, m.ectyper_serotype) AS serotype,
    m.n_amr_genes,
    m.read_pairs_before * 2       AS raw_reads,
    m.bases_before                AS raw_bases,
    m.q30_before                  AS raw_q30,
    m.read_length                 AS raw_read_length,
    m.read_pairs_after * 2        AS reads,
    m.bases_after                 AS bases,
    m.q30_after                   AS q30,
    m.trimmed_read_length,
    m.pct_reads_passed,
    m.n_contigs,
    m.assembly_length,
    m.n50,
    m.gc,
    (SELECT c.value_num FROM qc_check c
      WHERE c.version_id = rv.id AND c.metric = 'derived.depth'
      ORDER BY c.ordinal LIMIT 1) AS depth,
    m.completeness,
    m.contamination
FROM sample_run sr
JOIN run r ON r.id = sr.run_id
LEFT JOIN result_version rv ON rv.id = sr.current_version_id
LEFT JOIN LATERAL (
    SELECT
        max(v.value_num)  FILTER (WHERE v.metric_key = 'fastp.read_pairs_before_filter') AS read_pairs_before,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'fastp.bases_before_filter') AS bases_before,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'fastp.pct_q30_before_filter') AS q30_before,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'fastp.read_length') AS read_length,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'fastp.read_pairs_after_filter') AS read_pairs_after,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'fastp.bases_after_filter') AS bases_after,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'fastp.pct_q30_after_filter') AS q30_after,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'fastp.mean_read_length_after_filter') AS trimmed_read_length,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'fastp.pct_reads_passed_filter') AS pct_reads_passed,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'seqkit.n_contigs') AS n_contigs,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'seqkit.total_length') AS assembly_length,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'seqkit.n50') AS n50,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'quast.pct_gc') AS gc,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'checkm2.pct_completeness') AS completeness,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'checkm2.pct_contamination') AS contamination,
        max(v.value_text) FILTER (WHERE v.metric_key = 'mlst.sequence_type') AS mlst_st,
        max(v.value_text) FILTER (WHERE v.metric_key = 'seqsero2.serotype') AS seqsero2_serotype,
        max(v.value_text) FILTER (WHERE v.metric_key = 'ectyper.serotype') AS ectyper_serotype,
        max(v.value_num)  FILTER (WHERE v.metric_key = 'amrfinder.n_amr_genes') AS n_amr_genes
    FROM tool_result tr
    JOIN metric_value v ON v.tool_result_id = tr.id
    WHERE tr.version_id = rv.id
) m ON true
WITH DATA;

CREATE UNIQUE INDEX sample_run_summary_pk ON sample_run_summary (sample_run_id);
CREATE INDEX sample_run_summary_run_idx ON sample_run_summary (run_id);
CREATE INDEX sample_run_summary_date_idx ON sample_run_summary (run_date);
CREATE INDEX sample_run_summary_verdict_idx ON sample_run_summary (verdict);
CREATE INDEX sample_run_summary_species_idx ON sample_run_summary (species);
CREATE INDEX sample_run_summary_sha_idx ON sample_run_summary (thresholds_sha256);
CREATE INDEX sample_run_summary_profile_idx ON sample_run_summary (profile);

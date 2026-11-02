"""Pydantic models of the API. Role-dependent fields live in subclasses (``...Tech``/
``...Contact``) so that, for ``viewer``, they are absent from the response, not null."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


def _json_number(value: Decimal | int | float | None) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value() and value.as_tuple().exponent == 0:
            return int(value)
        return float(value)
    return value


Number = Annotated[
    Decimal | int | float | None,
    PlainSerializer(_json_number, return_type=int | float | None, when_used="json"),
]
Scalar = Annotated[
    Decimal | int | float | str | bool | None,
    PlainSerializer(
        lambda v: (
            _json_number(v)
            if isinstance(v, (Decimal, int, float)) and not isinstance(v, bool)
            else v
        ),
        return_type=int | float | str | bool | None,
        when_used="json",
    ),
]
Verdict = Literal["PASS", "WARN", "FAIL"]
Role = Literal["admin", "bioinformatician", "viewer"]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------- auth
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1000)


class MeOut(Out):
    id: int
    username: str
    role: Role
    csrf_token: str


# ---------------------------------------------------------------------- references
class OwnerRef(Out):
    id: int
    full_name: str | None
    erased: bool


class OrderRef(Out):
    id: int
    order_code: str
    owner: OwnerRef | None


class RunRef(Out):
    run_code: str
    run_date: dt.date | None


class ResultRef(Out):
    sample_run_id: int
    run_code: str
    run_date: dt.date | None
    verdict: Verdict | None
    has_results: bool


# ---------------------------------------------------------------------- results
class ResultItem(Out):
    sample_run_id: int
    run_code: str
    run_date: dt.date | None
    sample_code: str
    sample_id: int | None
    version_no: int | None
    n_versions: int
    has_results: bool
    has_qc: bool
    has_report: bool
    verdict: Verdict | None
    profile: str | None
    read_length_profile: str | None
    thresholds_sha256: str | None
    species: str | None
    mlst_st: str | None
    serotype: str | None
    n_amr_genes: Number
    raw_reads: Number
    raw_bases: Number
    raw_q30: Number
    raw_read_length: Number
    reads: Number
    bases: Number
    q30: Number
    trimmed_read_length: Number
    pct_reads_passed: Number
    n_contigs: Number
    assembly_length: Number
    n50: Number
    gc: Number
    depth: Number
    completeness: Number
    contamination: Number
    orders: list[OrderRef]


class CheckOut(Out):
    ordinal: int
    metric: str
    label: str | None
    value: Scalar
    unit: str | None
    rule: dict[str, Number]
    required: bool
    status: Literal["PASS", "WARN", "FAIL", "NA"]
    reason: str | None


class MetricOut(Out):
    key: str
    name: str
    label: str
    unit: str
    value_type: str
    value: Scalar
    is_null: bool


class ToolOut(Out):
    tool: str
    namespace: str
    status: Literal["ok", "empty", "skipped", "failed", "missing"]
    messages: list[str] | None
    tool_version: str
    database_version: str | None
    parser_name: str
    parser_version: str
    schema_version: str
    metrics: list[MetricOut]
    absent_metrics: list[str] = Field(description="dictionary keys of this tool with no value row")


class AmrHitOut(Out):
    ordinal: int
    symbol: str | None
    name: str | None
    type: str | None
    subtype: str | None
    class_: str | None = Field(serialization_alias="class")
    subclass: str | None
    method: str | None
    pct_identity: Number
    pct_coverage: Number
    scope: str | None
    contig: str | None
    start_pos: int | None
    stop_pos: int | None
    strand: str | None
    accession: str | None


class AbundanceOut(Out):
    ordinal: int
    name: str | None
    taxid: int | None
    reads: int | None
    pct: Number


class Thresholds(Out):
    sha256: str
    profile: str
    read_length_profile: str | None
    species: str | None
    chain: list[str]


class Context(Out):
    expected_taxid: int | None
    read_length: Number
    depth_basis: str | None


class Typing(Out):
    mlst_scheme: str | None
    mlst_sequence_type: str | None
    mlst_alleles: dict[str, Any] | None
    seqsero2_serotype: str | None
    seqsero2_antigenic_profile: str | None
    ectyper_serotype: str | None
    ectyper_qc_flag: str | None = Field(description="ECTyper tool flag, not the QC verdict")
    report_species: dict[str, Any] | None


class Software(Out):
    pipeline: str | None
    pipeline_version: str | None
    nextflow_version: str | None
    groups: list[Any]
    other: list[Any]


class VersionDetail(Out):
    version_no: int
    created_at: dt.datetime
    is_current: bool
    verdict: Verdict | None
    has_qc: bool
    has_report: bool
    evaluator_version: str | None
    report_generator_version: str | None
    thresholds: Thresholds | None
    context: Context | None
    checks: list[CheckOut]
    reasons: list[str]
    advisory: list[str]
    notes: list[str]
    unused_inputs: list[str]
    tools: list[ToolOut]
    typing: Typing
    amr_hits: list[AmrHitOut]
    abundances: list[AbundanceOut]
    software: Software | None


class DocumentOut(Out):
    kind: str
    tool: str | None
    file_name: str
    sha256: str


class ToolTechnical(Out):
    inputs: list[Any] | None
    data: dict[str, Any] | None


class Technical(Out):
    thresholds_file: str | None
    qc_inputs: list[Any] | None
    meta: dict[str, Any] | None
    load_warnings: list[str]
    load_batch_id: int
    load_invoked_by: str
    load_source_dir: str
    documents: list[DocumentOut]
    tools: dict[str, ToolTechnical]


class VersionDetailTech(VersionDetail):
    technical: Technical


class SampleRef(Out):
    id: int
    sample_code: str
    metadata: dict[str, Any]


class ResultDetail(Out):
    sample_run_id: int
    sample_code: str
    run: RunRef
    sample: SampleRef | None
    orders: list[OrderRef]
    n_versions: int
    version: VersionDetailTech | VersionDetail | None


class CheckChange(Out):
    metric: str
    old_status: str | None
    new_status: str | None


class VersionSummary(Out):
    version_no: int
    created_at: dt.datetime
    is_current: bool
    verdict: Verdict | None
    has_qc: bool
    has_report: bool
    thresholds_sha256: str | None
    profile: str | None
    check_changes: list[CheckChange] = Field(description="differences to the previous version")


class SetCurrentIn(BaseModel):
    version_no: int = Field(ge=1)


class RelinkIn(BaseModel):
    sample_id: int | None = Field(description="biological sample to link; null unlinks")


# ---------------------------------------------------------------------- runs
class RunOut(Out):
    run_code: str
    run_date: dt.date | None
    run_date_source: str | None
    n_samples: int
    n_pass: int
    n_warn: int
    n_fail: int
    n_missing: int


class RunDetail(RunOut):
    run_document_summary: dict[str, int] | None
    summary_matches_run_document: bool | None


class RunPatch(BaseModel):
    run_date: dt.date | None


class OutlierOut(Out):
    column: str
    label: str
    unit: str | None
    sample_run_id: int
    sample_code: str
    value: Number
    low_fence: Number
    high_fence: Number
    direction: Literal["low", "high"]


# ---------------------------------------------------------------------- metrics and trends
class MetricDefinitionOut(Out):
    key: str
    source: Literal["dictionary", "check"]
    tool: str | None
    namespace: str | None
    unit: str | None
    value_type: str
    numeric: bool
    range_min: Number
    range_max: Number
    label: str
    label_en: str | None
    description: str | None


class TrendPoint(Out):
    sample_run_id: int
    sample_code: str
    run_code: str
    run_date: dt.date
    value: Number
    verdict: Verdict | None
    species: str | None
    profile: str | None
    thresholds_sha256: str | None


class TrendGroup(Out):
    key: str | None
    n: int
    min: Number
    q1: Number
    median: Number
    q3: Number
    max: Number


class ThresholdChange(Out):
    run_date: dt.date
    run_code: str
    previous_sha256: str
    sha256: str


class TrendOut(Out):
    metric: str
    label: str
    unit: str | None
    points: list[TrendPoint]
    groups: list[TrendGroup]
    group_by: str
    threshold_changes: list[ThresholdChange]
    excluded_without_date: int


# ---------------------------------------------------------------------- owners, orders, samples
class OwnerOut(Out):
    id: int
    full_name: str | None
    erased: bool
    erased_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime
    n_orders: int


class OwnerContactOut(OwnerOut):
    email: str | None


EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class OwnerIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254, pattern=EMAIL_PATTERN)


class OwnerPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254, pattern=EMAIL_PATTERN)


class SampleBrief(Out):
    id: int
    sample_code: str


class OrderOut(Out):
    id: int
    order_code: str
    owner: OwnerRef | None
    created_at: dt.datetime
    updated_at: dt.datetime
    n_samples: int


class OrderTechOut(OrderOut):
    meta: dict[str, Any] | None


class OrderDetail(OrderOut):
    samples: list[SampleBrief]


class OrderTechDetail(OrderDetail):
    meta: dict[str, Any] | None


class OrderIn(BaseModel):
    order_code: str = Field(min_length=1, max_length=100)
    owner_id: int | None = None


class OrderPatch(BaseModel):
    order_code: str | None = Field(default=None, min_length=1, max_length=100)
    owner_id: int | None = None


class AssignIn(BaseModel):
    sample_ids: list[int] = Field(min_length=1, max_length=1000)


class SampleOut(Out):
    id: int
    sample_code: str
    metadata: dict[str, Any]
    missing_required: list[str]
    orders: list[OrderRef]
    results: list[ResultRef]
    created_at: dt.datetime
    updated_at: dt.datetime


class SampleIn(BaseModel):
    sample_code: str = Field(min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SamplePatch(BaseModel):
    sample_code: str | None = Field(default=None, min_length=1, max_length=200)
    metadata: dict[str, Any] | None = Field(
        default=None, description="merged into the stored metadata; a null value removes a key"
    )


class SampleFieldOut(Out):
    id: int
    key: str
    label: str
    data_type: Literal["text", "number", "date", "choice"]
    choices: list[str] | None
    required: bool
    ordinal: int
    is_active: bool


class SampleFieldIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=60)
    label: str = Field(min_length=1, max_length=200)
    data_type: Literal["text", "number", "date", "choice"]
    choices: list[str] | None = None
    required: bool = False
    ordinal: int = 100


class SampleFieldPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    choices: list[str] | None = None
    required: bool | None = None
    ordinal: int | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------- users, audit
class UserOut(Out):
    id: int
    username: str
    role: Role
    is_active: bool
    locked: bool
    created_at: dt.datetime
    last_login_at: dt.datetime | None


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$")
    role: Role
    password: str = Field(min_length=12, max_length=1000)


class UserPatch(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class PasswordIn(BaseModel):
    password: str = Field(min_length=12, max_length=1000)


class AuditOut(Out):
    id: int
    occurred_at: dt.datetime
    actor_label: str
    action: str
    entity_type: str
    entity_id: str
    changes: dict[str, Any]


class HealthOut(BaseModel):
    status: str
    database: str | None = None
    migration: str | None = None

"""SQLAlchemy 2 ORM models. The schema itself is created by the Alembic migration
(``migrations/versions/0001_initial.sql``); ``tests/test_schema.py`` checks both agree."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

TS = TIMESTAMP(timezone=True)


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


class AppUser(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = _pk()
    username: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    failed_logins: Mapped[int] = mapped_column(Integer, server_default="0")
    locked_until: Mapped[dt.datetime | None] = mapped_column(TS)
    created_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())
    last_login_at: Mapped[dt.datetime | None] = mapped_column(TS)


class UserSession(Base):
    __tablename__ = "user_session"
    token_hash: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"))
    csrf_token: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())
    last_seen_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())
    expires_at: Mapped[dt.datetime] = mapped_column(TS)


class MetricDictionaryImport(Base):
    __tablename__ = "metric_dictionary_import"
    id: Mapped[int] = _pk()
    file_name: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(CHAR(64), unique=True)
    kind: Mapped[str] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(Text)
    n_entries: Mapped[int] = mapped_column(Integer)
    n_added: Mapped[int] = mapped_column(Integer)
    n_changed: Mapped[int] = mapped_column(Integer)
    imported_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())
    imported_by: Mapped[str] = mapped_column(Text)


class MetricDefinition(Base):
    __tablename__ = "metric_definition"
    __table_args__ = (UniqueConstraint("tool", "metric"),)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    tool: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(Text)
    range_min: Mapped[Decimal | None] = mapped_column(Numeric)
    range_max: Mapped[Decimal | None] = mapped_column(Numeric)
    label: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    added_in_import_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("metric_dictionary_import.id")
    )


class MetricLabel(Base):
    __tablename__ = "metric_label"
    metric_key: Mapped[str] = mapped_column(
        Text, ForeignKey("metric_definition.key"), primary_key=True
    )
    lang: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)


class Owner(Base):
    __tablename__ = "owner"
    id: Mapped[int] = _pk()
    full_name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())
    erased_at: Mapped[dt.datetime | None] = mapped_column(TS)


class SampleOrder(Base):
    __tablename__ = "sample_order"
    id: Mapped[int] = _pk()
    order_code: Mapped[str] = mapped_column(Text, unique=True)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("owner.id"))
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())


class SampleFieldDefinition(Base):
    __tablename__ = "sample_field_definition"
    id: Mapped[int] = _pk()
    key: Mapped[str] = mapped_column(Text, unique=True)
    label: Mapped[str] = mapped_column(Text)
    data_type: Mapped[str] = mapped_column(Text)
    choices: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    required: Mapped[bool] = mapped_column(Boolean, server_default="false")
    ordinal: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())


class Sample(Base):
    __tablename__ = "sample"
    id: Mapped[int] = _pk()
    sample_code: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default="{}")
    created_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())


class OrderSample(Base):
    __tablename__ = "order_sample"
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sample_order.id"), primary_key=True
    )
    sample_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sample.id"), primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    linked_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())


class LoadBatch(Base):
    __tablename__ = "load_batch"
    id: Mapped[int] = _pk()
    started_at: Mapped[dt.datetime] = mapped_column(TS)
    finished_at: Mapped[dt.datetime | None] = mapped_column(TS)
    invoked_by: Mapped[str] = mapped_column(Text)
    qcdb_version: Mapped[str] = mapped_column(Text)
    source_dir: Mapped[str] = mapped_column(Text)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB)
    counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class SourceDocument(Base):
    __tablename__ = "source_document"
    id: Mapped[int] = _pk()
    sha256: Mapped[str] = mapped_column(CHAR(64), unique=True)
    kind: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    first_batch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("load_batch.id"))


class Run(Base):
    __tablename__ = "run"
    id: Mapped[int] = _pk()
    run_code: Mapped[str] = mapped_column(Text, unique=True)
    run_date: Mapped[dt.date | None] = mapped_column(Date)
    run_date_source: Mapped[str | None] = mapped_column(Text)
    run_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("source_document.id")
    )
    created_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())


class RunMembership(Base):
    __tablename__ = "run_membership"
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("run.id"), primary_key=True)
    sample_code: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    source_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    run_json_entry: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class SampleRun(Base):
    __tablename__ = "sample_run"
    __table_args__ = (
        UniqueConstraint("run_id", "sample_code"),
        ForeignKeyConstraint(
            ["current_version_id", "id"],
            ["result_version.id", "result_version.sample_run_id"],
            name="sample_run_current_fk",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
    )
    id: Mapped[int] = _pk()
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("run.id"))
    sample_code: Mapped[str] = mapped_column(Text)
    sample_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("sample.id"))
    current_version_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())


class ResultVersion(Base):
    __tablename__ = "result_version"
    __table_args__ = (
        UniqueConstraint("sample_run_id", "version_no"),
        UniqueConstraint("sample_run_id", "fingerprint"),
        UniqueConstraint("id", "sample_run_id"),
    )
    id: Mapped[int] = _pk()
    sample_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sample_run.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    load_batch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("load_batch.id"))
    fingerprint: Mapped[str] = mapped_column(CHAR(64))
    created_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())
    has_qc: Mapped[bool] = mapped_column(Boolean)
    has_report: Mapped[bool] = mapped_column(Boolean)
    qc_document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("source_document.id"))
    verdict: Mapped[str | None] = mapped_column(Text)
    evaluator_version: Mapped[str | None] = mapped_column(Text)
    thresholds_file: Mapped[str | None] = mapped_column(Text)
    thresholds_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    profile: Mapped[str | None] = mapped_column(Text)
    read_length_profile: Mapped[str | None] = mapped_column(Text)
    threshold_species: Mapped[str | None] = mapped_column(Text)
    threshold_chain: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    expected_taxid: Mapped[int | None] = mapped_column(Integer)
    context_read_length: Mapped[Decimal | None] = mapped_column(Numeric)
    depth_basis: Mapped[str | None] = mapped_column(Text)
    reasons: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    advisory: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    notes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    unused_inputs: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    qc_inputs: Mapped[list[Any] | None] = mapped_column(JSONB)
    report_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("source_document.id")
    )
    report_run_id: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    report_generator_version: Mapped[str | None] = mapped_column(Text)
    pipeline: Mapped[str | None] = mapped_column(Text)
    pipeline_version: Mapped[str | None] = mapped_column(Text)
    nextflow_version: Mapped[str | None] = mapped_column(Text)
    software: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    typing_species: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    load_warnings: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")

    tool_results: Mapped[list[ToolResult]] = relationship(
        back_populates="version", cascade="all, delete-orphan", passive_deletes=True
    )
    checks: Mapped[list[QcCheck]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="QcCheck.ordinal"
    )


class ToolResult(Base):
    __tablename__ = "tool_result"
    __table_args__ = (UniqueConstraint("version_id", "tool"),)
    id: Mapped[int] = _pk()
    version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("result_version.id", ondelete="CASCADE")
    )
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("source_document.id"))
    tool: Mapped[str] = mapped_column(Text)
    namespace: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    messages: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    tool_version: Mapped[str] = mapped_column(Text)
    database_version: Mapped[str | None] = mapped_column(Text)
    parser_name: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[str] = mapped_column(Text)
    inputs: Mapped[list[Any] | None] = mapped_column(JSONB)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    version: Mapped[ResultVersion] = relationship(back_populates="tool_results")
    metrics: Mapped[list[MetricValue]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )
    amr_hits: Mapped[list[AmrHit]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )
    abundances: Mapped[list[SpeciesAbundance]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class MetricValue(Base):
    __tablename__ = "metric_value"
    __table_args__ = (UniqueConstraint("tool_result_id", "metric_key"),)
    id: Mapped[int] = _pk()
    tool_result_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tool_result.id", ondelete="CASCADE")
    )
    metric_key: Mapped[str] = mapped_column(Text, ForeignKey("metric_definition.key"))
    unit: Mapped[str] = mapped_column(Text)
    value_num: Mapped[Decimal | None] = mapped_column(Numeric)
    value_text: Mapped[str | None] = mapped_column(Text)
    value_bool: Mapped[bool | None] = mapped_column(Boolean)


class QcCheck(Base):
    __tablename__ = "qc_check"
    __table_args__ = (UniqueConstraint("version_id", "ordinal"),)
    id: Mapped[int] = _pk()
    version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("result_version.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(SmallInteger)
    metric: Mapped[str] = mapped_column(Text)
    value_num: Mapped[Decimal | None] = mapped_column(Numeric)
    value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)
    rule: Mapped[dict[str, Any]] = mapped_column(JSONB)
    required: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)


class AmrHit(Base):
    __tablename__ = "amr_hit"
    __table_args__ = (UniqueConstraint("tool_result_id", "ordinal"),)
    id: Mapped[int] = _pk()
    tool_result_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tool_result.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    symbol: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text)
    subtype: Mapped[str | None] = mapped_column(Text)
    class_: Mapped[str | None] = mapped_column("class", Text)
    subclass: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(Text)
    pct_identity: Mapped[Decimal | None] = mapped_column(Numeric)
    pct_coverage: Mapped[Decimal | None] = mapped_column(Numeric)
    scope: Mapped[str | None] = mapped_column(Text)
    contig: Mapped[str | None] = mapped_column(Text)
    start_pos: Mapped[int | None] = mapped_column(BigInteger)
    stop_pos: Mapped[int | None] = mapped_column(BigInteger)
    strand: Mapped[str | None] = mapped_column(Text)
    accession: Mapped[str | None] = mapped_column(Text)


class SpeciesAbundance(Base):
    __tablename__ = "species_abundance"
    __table_args__ = (UniqueConstraint("tool_result_id", "ordinal"),)
    id: Mapped[int] = _pk()
    tool_result_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tool_result.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(Text)
    taxid: Mapped[int | None] = mapped_column(Integer)
    reads: Mapped[int | None] = mapped_column(BigInteger)
    pct: Mapped[Decimal | None] = mapped_column(Numeric)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = _pk()
    occurred_at: Mapped[dt.datetime] = mapped_column(TS, server_default=func.now())
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app_user.id"))
    actor_label: Mapped[str] = mapped_column(Text)
    load_batch_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("load_batch.id"))
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str] = mapped_column(Text)
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB)

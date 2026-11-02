"""Shared API helpers: pagination, sorting, path masking, CSV, audit, summary view."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Annotated, Any, Generic, TypeVar

from fastapi import HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    text,
)
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from qcdb.api.security import Principal
from qcdb.db.models import AuditLog
from qcdb.summary_columns import SUMMARY_COLUMNS

T = TypeVar("T")

# The materialized view (not part of the ORM metadata, which mirrors tables only).
_view_metadata = MetaData()
SUMMARY_VIEW = Table(
    "sample_run_summary",
    _view_metadata,
    Column("sample_run_id", BigInteger, primary_key=True),
    Column("run_id", BigInteger),
    Column("run_code", Text),
    Column("run_date", Date),
    Column("sample_code", Text),
    Column("sample_id", BigInteger),
    Column("version_id", BigInteger),
    Column("version_no", Integer),
    Column("n_versions", BigInteger),
    Column("has_results", Boolean),
    Column("has_qc", Boolean),
    Column("has_report", Boolean),
    Column("verdict", Text),
    Column("profile", Text),
    Column("read_length_profile", Text),
    Column("thresholds_sha256", Text),
    Column("species", Text),
    Column("mlst_st", Text),
    Column("serotype", Text),
    Column("n_amr_genes", Numeric),
    *(Column(c.id, Numeric) for c in SUMMARY_COLUMNS),
)

# Units and Polish labels of the summary columns (CSV second header row, UI).
SUMMARY_LABELS: dict[str, tuple[str, str | None]] = {
    "raw_reads": ("Odczyty (surowe)", "reads"),
    "raw_bases": ("Zasady (surowe)", "bp"),
    "raw_q30": ("Q30 (surowe)", "percent"),
    "raw_read_length": ("Długość odczytu (surowe)", "bp"),
    "reads": ("Odczyty po QC", "reads"),
    "bases": ("Zasady po QC", "bp"),
    "q30": ("Q30 po QC", "percent"),
    "trimmed_read_length": ("Długość odczytu po QC", "bp"),
    "pct_reads_passed": ("% odczytów po filtrze", "percent"),
    "n_contigs": ("Kontigi", "contigs"),
    "assembly_length": ("Długość złożenia", "bp"),
    "n50": ("N50", "bp"),
    "gc": ("GC", "percent"),
    "depth": ("Pokrycie", "x"),
    "completeness": ("Kompletność", "percent"),
    "contamination": ("Zanieczyszczenie", "percent"),
}


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


PageParam = Annotated[int, Query(ge=1, description="1-based page number")]
PageSizeParam = Annotated[int, Query(ge=1, le=500)]


def parse_sort(
    sort: str | None, allowed: Mapping[str, Any], default: Sequence[str]
) -> list[ColumnElement[Any]]:
    """``sort=-run_date,sample_code`` -> ORDER BY clauses; unknown fields are a 422."""
    fields = [f.strip() for f in (sort or "").split(",") if f.strip()] or list(default)
    clauses: list[ColumnElement[Any]] = []
    for field in fields:
        desc = field.startswith("-")
        name = field[1:] if desc else field
        if name not in allowed:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"cannot sort by {name!r}; allowed: {', '.join(sorted(allowed))}",
            )
        column = allowed[name]
        clauses.append(column.desc().nulls_last() if desc else column.asc().nulls_last())
    return clauses


_PATH_RE = re.compile(r"(?<![\w.:-])(?:[A-Za-z]:)?/?(?:[\w.+~-]+/)+([\w.+~-]+)")


def mask_paths(message: str) -> str:
    """D8: replace path-like tokens with their basename (heuristic)."""
    return _PATH_RE.sub(r"\1", message)


def audit(
    db: Session,
    principal: Principal,
    action: str,
    entity_type: str,
    entity_id: object,
    changes: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            actor_user_id=principal.user_id,
            actor_label=principal.label,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            changes=changes,
        )
    )


def refresh_summary(db: Session) -> None:
    """Refresh the sample-table view; call after committing changes it depends on."""
    with db.begin():
        db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY sample_run_summary"))


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, Decimal, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        value = ";".join(_csv_cell(v) for v in value)
    text_value = str(value)
    if text_value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text_value  # neutralise spreadsheet formulas
    return text_value


def csv_text(keys: Sequence[str], labels: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    """Q14: comma, decimal point, row 1 = keys, row 2 = Polish labels [unit]."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(keys)
    writer.writerow(labels)
    for row in rows:
        writer.writerow([_csv_cell(v) for v in row])
    return out.getvalue()

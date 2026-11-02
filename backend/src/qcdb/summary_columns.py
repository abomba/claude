"""Run-document summary columns (D3). Must match the ``sample_run_summary`` materialized view
in the initial migration; ``tests/test_loader.py`` checks the two agree on the fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Column:
    id: str
    metric: str  # metric key, or a qc check metric when ``from_check``
    factor: int = 1
    from_check: bool = False


SUMMARY_COLUMNS: tuple[Column, ...] = (
    Column("raw_reads", "fastp.read_pairs_before_filter", factor=2),
    Column("raw_bases", "fastp.bases_before_filter"),
    Column("raw_q30", "fastp.pct_q30_before_filter"),
    Column("raw_read_length", "fastp.read_length"),
    Column("reads", "fastp.read_pairs_after_filter", factor=2),
    Column("bases", "fastp.bases_after_filter"),
    Column("q30", "fastp.pct_q30_after_filter"),
    Column("trimmed_read_length", "fastp.mean_read_length_after_filter"),
    Column("pct_reads_passed", "fastp.pct_reads_passed_filter"),
    Column("n_contigs", "seqkit.n_contigs"),
    Column("assembly_length", "seqkit.total_length"),
    Column("n50", "seqkit.n50"),
    Column("gc", "quast.pct_gc"),
    Column("depth", "derived.depth", from_check=True),
    Column("completeness", "checkm2.pct_completeness"),
    Column("contamination", "checkm2.pct_contamination"),
)


def _number(value: Any) -> int | Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return None
    return value


def summary_values(
    metrics: dict[str, Any], checks: list[dict[str, Any]]
) -> dict[str, int | Decimal | None]:
    """Compute the summary columns from ``{metric key: value}`` and qc ``checks``."""
    check_values: dict[str, Any] = {}
    for check in checks:
        check_values.setdefault(check["metric"], check["value"])
    result: dict[str, int | Decimal | None] = {}
    for col in SUMMARY_COLUMNS:
        raw = check_values.get(col.metric) if col.from_check else metrics.get(col.metric)
        value = _number(raw)
        result[col.id] = None if value is None else value * col.factor
    return result

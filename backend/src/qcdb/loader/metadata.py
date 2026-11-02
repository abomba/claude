"""``qcdb load --metadata FILE``: CSV/TSV import of run dates, sample metadata and order links.

Columns: ``sample_id`` (required), optional ``run_id``, ``run_date`` (YYYY-MM-DD), ``order_id``,
and one column per configured sample field key. Empty cells change nothing.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from qcdb.db.models import OrderSample, Run, Sample, SampleFieldDefinition, SampleOrder, SampleRun

if TYPE_CHECKING:
    from qcdb.loader.core import Loader

FIXED_COLUMNS = ("sample_id", "run_id", "run_date", "order_id")


class RowError(Exception):
    pass


def parse_field_value(field: SampleFieldDefinition, raw: str) -> Any:
    """Validate one metadata value against its field definition; returns the JSON value."""
    if field.data_type == "text":
        return raw
    if field.data_type == "number":
        try:
            value = Decimal(raw)
        except InvalidOperation:
            raise RowError(f"{field.key}: {raw!r} is not a number") from None
        if not value.is_finite():
            raise RowError(f"{field.key}: {raw!r} is not a number")
        return value
    if field.data_type == "date":
        try:
            return dt.date.fromisoformat(raw).isoformat()
        except ValueError:
            raise RowError(f"{field.key}: {raw!r} is not a date (YYYY-MM-DD)") from None
    if field.data_type == "choice":
        if raw not in (field.choices or []):
            raise RowError(f"{field.key}: {raw!r} is not one of {', '.join(field.choices or [])}")
        return raw
    raise RowError(f"{field.key}: unsupported field type {field.data_type!r}")


def apply_metadata(loader: Loader, path: Path) -> None:
    report = loader.report
    counts = report.documents["metadata"]
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        rows = list(csv.DictReader(io.StringIO(text), delimiter=delimiter, strict=True))
        header = list(rows[0].keys()) if rows else []
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        report.unreadable.append(f"{path}: unreadable metadata file ({exc})")
        return
    if "sample_id" not in header:
        report.unreadable.append(f"{path}: metadata file has no 'sample_id' column")
        return
    with loader._read():
        fields = {f.key: f for f in loader.session.scalars(select(SampleFieldDefinition))}
    unknown = [c for c in header if c not in FIXED_COLUMNS and c not in fields]
    inactive = [c for c in header if c in fields and not fields[c].is_active]
    if unknown or inactive:
        problems = [f"unknown column(s): {', '.join(unknown)}"] if unknown else []
        problems += [f"inactive field(s): {', '.join(inactive)}"] if inactive else []
        report.rejected.append(f"{path}: {'; '.join(problems)}")
        counts["rejected"] += len(rows)
        return
    for line_no, row in enumerate(rows, start=2):
        where = f"{path} line {line_no}"
        try:
            with loader._unit():
                changed = _apply_row(loader, row, fields)
            counts["loaded" if changed else "identical"] += 1
        except RowError as exc:
            report.rejected.append(f"{where}: {exc}")
            counts["rejected"] += 1
        except SQLAlchemyError as exc:
            report.rejected.append(f"{where}: database error {exc.__class__.__name__}")
            counts["rejected"] += 1


def _cell(row: dict[str, Any], column: str) -> str | None:
    value = row.get(column)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _apply_row(
    loader: Loader, row: dict[str, Any], fields: dict[str, SampleFieldDefinition]
) -> bool:
    session = loader.session
    sample_code = _cell(row, "sample_id")
    if sample_code is None:
        raise RowError("empty sample_id")
    run_code = _cell(row, "run_id")
    changed = False

    run: Run | None = None
    if run_code is not None:
        run = session.scalar(select(Run).where(Run.run_code == run_code))
        if run is None:
            raise RowError(f"run {run_code!r} is not in the database")
    run_date_text = _cell(row, "run_date")
    if run_date_text is not None:
        if run is None:
            raise RowError("run_date given without run_id")
        try:
            run_date = dt.date.fromisoformat(run_date_text)
        except ValueError:
            raise RowError(f"run_date {run_date_text!r} is not a date (YYYY-MM-DD)") from None
        if run.run_date is None:
            run.run_date, run.run_date_source = run_date, "metadata"
            loader._audit(
                "update",
                "run",
                run.run_code,
                {"run_date": {"old": None, "new": run_date.isoformat()}},
            )
            changed = True
        elif run.run_date != run_date:
            raise RowError(
                f"run {run.run_code!r} already has date {run.run_date.isoformat()}; "
                "change it in the web application"
            )

    sample = _find_sample(loader, sample_code, run)
    values = {
        key: parse_field_value(fields[key], cell)
        for key in fields
        if (cell := _cell(row, key)) is not None
    }
    if values:
        if sample is None:
            sample = Sample(sample_code=sample_code, metadata_={})
            session.add(sample)
            session.flush()
            loader._audit("create", "sample", sample.id, {"sample_code": sample_code})
        merged = dict(sample.metadata_)
        diff = {
            k: {"old": merged.get(k), "new": v} for k, v in values.items() if merged.get(k) != v
        }
        merged.update(values)
        missing = [
            f.key for f in fields.values() if f.is_active and f.required and f.key not in merged
        ]
        if missing:
            raise RowError(f"required field(s) missing: {', '.join(missing)}")
        if diff:
            sample.metadata_ = merged
            session.flush()
            loader._audit("update", "sample", sample.id, diff)
            changed = True

    order_code = _cell(row, "order_id")
    if order_code is not None:
        if sample is None:
            raise RowError(f"sample {sample_code!r} is not in the database; cannot link order")
        order = session.scalar(select(SampleOrder).where(SampleOrder.order_code == order_code))
        if order is None:
            order = SampleOrder(order_code=order_code)
            session.add(order)
            session.flush()
            loader._audit("create", "sample_order", order.id, {"order_code": order_code})
            changed = True
        if session.get(OrderSample, (order.id, sample.id)) is None:
            session.add(OrderSample(order_id=order.id, sample_id=sample.id, source="metadata"))
            session.flush()
            loader._audit(
                "link", "sample_order", order.id, {"sample_id": sample.id, "source": "metadata"}
            )
            changed = True
    return changed


def _find_sample(loader: Loader, sample_code: str, run: Run | None) -> Sample | None:
    session = loader.session
    if run is not None:
        sample_run = session.scalar(
            select(SampleRun).where(
                SampleRun.run_id == run.id, SampleRun.sample_code == sample_code
            )
        )
        if sample_run is None:
            raise RowError(f"sample {sample_code!r} is not in run {run.run_code!r}")
        if sample_run.sample_id is None:
            raise RowError(
                f"result {sample_code!r} in run {run.run_code!r} is not linked to a "
                "biological sample; link it in the web application"
            )
        return session.get(Sample, sample_run.sample_id)
    samples = session.scalars(select(Sample).where(Sample.sample_code == sample_code)).all()
    if len(samples) > 1:
        raise RowError(f"{len(samples)} samples share code {sample_code!r}; add run_id")
    return samples[0] if samples else None

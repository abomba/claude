"""Metric dictionary: parsing ``<tool>.<metric>|unit|type|range|label|description`` files and
importing them into ``metric_definition`` (``qcdb import-dictionary``)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from importlib import resources
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from qcdb.db.models import AuditLog, MetricDefinition, MetricDictionaryImport, MetricLabel
from qcdb.jsonio import sha256_hex

KEY_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
VALUE_TYPES = ("int", "float", "str", "bool")


class DictionaryFormatError(ValueError):
    """The dictionary file cannot be parsed."""


class DictionaryImportError(ValueError):
    """The dictionary file is well-formed but conflicts with the stored dictionary."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class MetricSpec:
    key: str
    tool: str
    metric: str
    unit: str
    value_type: str
    range_min: Decimal | None
    range_max: Decimal | None
    label: str
    description: str


@dataclass
class ImportResult:
    file_name: str
    n_entries: int
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    already_imported: bool = False


def _parse_bound(text: str, line_no: int) -> Decimal | None:
    if text == "":
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise DictionaryFormatError(f"line {line_no}: invalid range bound {text!r}") from None
    if not value.is_finite():
        raise DictionaryFormatError(f"line {line_no}: invalid range bound {text!r}")
    return value


def parse_dictionary(text: str) -> list[MetricSpec]:
    specs: list[MetricSpec] = []
    seen: set[str] = set()
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) != 6:
            raise DictionaryFormatError(f"line {line_no}: expected 6 '|'-separated fields")
        key, unit, value_type, range_text, label, description = (p.strip() for p in parts)
        if not KEY_RE.match(key):
            raise DictionaryFormatError(f"line {line_no}: invalid key {key!r}")
        if key in seen:
            raise DictionaryFormatError(f"line {line_no}: duplicate key {key!r}")
        if value_type not in VALUE_TYPES:
            raise DictionaryFormatError(f"line {line_no}: invalid type {value_type!r}")
        if not unit or not label:
            raise DictionaryFormatError(f"line {line_no}: unit and label are required")
        range_min = range_max = None
        if range_text:
            if ".." not in range_text:
                raise DictionaryFormatError(f"line {line_no}: invalid range {range_text!r}")
            low, high = range_text.split("..", 1)
            range_min, range_max = _parse_bound(low, line_no), _parse_bound(high, line_no)
            if value_type in ("str", "bool"):
                raise DictionaryFormatError(f"line {line_no}: range given for {value_type} metric")
        tool, metric = key.split(".", 1)
        seen.add(key)
        specs.append(
            MetricSpec(
                key, tool, metric, unit, value_type, range_min, range_max, label, description
            )
        )
    if not specs:
        raise DictionaryFormatError("dictionary file is empty")
    return specs


def default_dictionary_path() -> Path:
    return Path(str(resources.files("qcdb") / "data" / "metric_dictionary.psv"))


def load_dictionary(session: Session) -> dict[str, MetricSpec]:
    rows = session.scalars(select(MetricDefinition)).all()
    return {
        r.key: MetricSpec(
            r.key,
            r.tool,
            r.metric,
            r.unit,
            r.value_type,
            r.range_min,
            r.range_max,
            r.label,
            r.description,
        )
        for r in rows
    }


def import_dictionary(session: Session, path: Path, actor: str) -> ImportResult:
    """Import a dictionary file in the caller's transaction. Raises on any conflict, leaving the
    session untouched; writes nothing when the file adds or changes nothing."""
    raw = path.read_bytes()
    sha = sha256_hex(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise DictionaryFormatError("dictionary file is not valid UTF-8") from None
    specs = parse_dictionary(text)
    result = ImportResult(file_name=path.name, n_entries=len(specs))
    if session.scalar(
        select(MetricDictionaryImport.id).where(MetricDictionaryImport.sha256 == sha)
    ):
        result.already_imported = True
        return result

    existing = {r.key: r for r in session.scalars(select(MetricDefinition))}
    new_keys = {s.key for s in specs}
    problems = [
        f"{key}: present in the database but missing from the file (metrics are never removed)"
        for key in sorted(set(existing) - new_keys)
    ]
    updates: list[tuple[MetricDefinition, dict[str, tuple[object, object]]]] = []
    for spec in specs:
        row = existing.get(spec.key)
        if row is None:
            result.added.append(spec.key)
            continue
        diff: dict[str, tuple[object, object]] = {}
        if row.unit != spec.unit:
            problems.append(f"{spec.key}: unit changed {row.unit!r} -> {spec.unit!r}")
        if (row.range_min, row.range_max) != (spec.range_min, spec.range_max):
            problems.append(f"{spec.key}: range changed")
        if row.value_type != spec.value_type:
            if (row.value_type, spec.value_type) == ("int", "float"):
                diff["value_type"] = (row.value_type, spec.value_type)
            elif (row.value_type, spec.value_type) == ("float", "int"):
                result.warnings.append(
                    f"{spec.key}: file says 'int', keeping the wider stored type 'float'"
                )
            else:
                problems.append(
                    f"{spec.key}: type changed {row.value_type!r} -> {spec.value_type!r}"
                )
        if row.label != spec.label:
            diff["label"] = (row.label, spec.label)
        if row.description != spec.description:
            diff["description"] = (row.description, spec.description)
        if diff:
            updates.append((row, diff))
            result.changed.append(spec.key)
    if problems:
        raise DictionaryImportError(problems)
    if not result.added and not result.changed:
        return result

    record = MetricDictionaryImport(
        file_name=path.name,
        sha256=sha,
        kind="dictionary",
        lang=None,
        n_entries=len(specs),
        n_added=len(result.added),
        n_changed=len(result.changed),
        imported_by=actor,
    )
    session.add(record)
    session.flush()
    by_key = {s.key: s for s in specs}
    for key in result.added:
        s = by_key[key]
        session.add(
            MetricDefinition(
                key=s.key,
                tool=s.tool,
                metric=s.metric,
                unit=s.unit,
                value_type=s.value_type,
                range_min=s.range_min,
                range_max=s.range_max,
                label=s.label,
                description=s.description,
                added_in_import_id=record.id,
            )
        )
    for row, diff in updates:
        for attr, (_, new) in diff.items():
            setattr(row, attr, new)
        session.add(
            AuditLog(
                actor_label=actor,
                action="update",
                entity_type="metric_definition",
                entity_id=row.key,
                changes={k: {"old": o, "new": n} for k, (o, n) in diff.items()},
            )
        )
    if result.added:
        session.add(
            AuditLog(
                actor_label=actor,
                action="import",
                entity_type="metric_dictionary_import",
                entity_id=str(record.id),
                changes={"added": result.added, "file": path.name},
            )
        )
    session.flush()
    return result


def import_labels(session: Session, path: Path, lang: str, actor: str) -> ImportResult:
    """Import ``key|label|description`` translations for ``lang`` into ``metric_label``."""
    if not re.fullmatch(r"[a-z]{2}", lang):
        raise DictionaryFormatError(f"invalid language code {lang!r}")
    raw = path.read_bytes()
    sha = sha256_hex(raw)
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise DictionaryFormatError("labels file is not valid UTF-8") from None
    entries: dict[str, tuple[str, str | None]] = {}
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) not in (2, 3) or not parts[1]:
            raise DictionaryFormatError(f"line {line_no}: expected 'key|label|description'")
        if parts[0] in entries:
            raise DictionaryFormatError(f"line {line_no}: duplicate key {parts[0]!r}")
        entries[parts[0]] = (parts[1], parts[2] if len(parts) == 3 and parts[2] else None)
    result = ImportResult(file_name=path.name, n_entries=len(entries))
    if session.scalar(
        select(MetricDictionaryImport.id).where(MetricDictionaryImport.sha256 == sha)
    ):
        result.already_imported = True
        return result
    known = set(session.scalars(select(MetricDefinition.key)))
    unknown = sorted(set(entries) - known)
    if unknown:
        raise DictionaryImportError([f"{k}: not in the metric dictionary" for k in unknown])
    current = {
        r.metric_key: r
        for r in session.scalars(select(MetricLabel).where(MetricLabel.lang == lang))
    }
    for key, (label, description) in entries.items():
        row = current.get(key)
        if row is None:
            session.add(
                MetricLabel(metric_key=key, lang=lang, label=label, description=description)
            )
            result.added.append(key)
        elif (row.label, row.description) != (label, description):
            row.label, row.description = label, description
            result.changed.append(key)
    if result.added or result.changed:
        session.add(
            MetricDictionaryImport(
                file_name=path.name,
                sha256=sha,
                kind="labels",
                lang=lang,
                n_entries=len(entries),
                n_added=len(result.added),
                n_changed=len(result.changed),
                imported_by=actor,
            )
        )
        session.add(
            AuditLog(
                actor_label=actor,
                action="import",
                entity_type="metric_label",
                entity_id=lang,
                changes={"added": result.added, "changed": result.changed, "file": path.name},
            )
        )
        session.flush()
    return result

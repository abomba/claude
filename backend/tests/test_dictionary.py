"""Metric dictionary parsing and ``import-dictionary`` rules."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from qcdb.db.models import AuditLog, MetricDefinition, MetricLabel
from qcdb.dictionary import (
    DictionaryFormatError,
    DictionaryImportError,
    default_dictionary_path,
    import_dictionary,
    import_labels,
    parse_dictionary,
)
from tests.conftest import snapshot

SPEC = Path(__file__).resolve().parents[2] / "spec" / "metric_dictionary.psv"


def test_packaged_dictionary_is_the_brief_plus_one_widening() -> None:
    packaged = parse_dictionary(default_dictionary_path().read_text(encoding="utf-8"))
    brief = parse_dictionary(SPEC.read_text(encoding="utf-8"))
    assert len(packaged) == len(brief) == 140
    differences = [
        (a.key, a.value_type, b.value_type) for a, b in zip(brief, packaged, strict=True) if a != b
    ]
    assert differences == [("fastp.insert_size_peak", "int", "float")]
    by_key = {s.key: s for s in packaged}
    assert by_key["checkm2.pct_contamination"].range_max is None
    assert by_key["quast.n_per_100kbp"].range_max == Decimal(100000)
    assert by_key["mlst.sequence_type"].value_type == "str"


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("fastp.x|bp|int|0..", "expected 6"),
        ("Fastp.x|bp|int|0..|L|D", "invalid key"),
        ("fastp.x|bp|integer|0..|L|D", "invalid type"),
        ("fastp.x|bp|int|0-100|L|D", "invalid range"),
        ("fastp.x|bp|str|0..|L|D", "range given"),
    ],
)
def test_parse_errors(line: str, message: str) -> None:
    with pytest.raises(DictionaryFormatError, match=message):
        parse_dictionary(line)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_seeded_and_reimport_is_noop(sessions: sessionmaker[Session], engine: Engine) -> None:
    before = snapshot(engine)
    with sessions() as s, s.begin():
        assert s.scalar(select(func.count()).select_from(MetricDefinition)) == 140
        result = import_dictionary(s, default_dictionary_path(), "test")
        assert result.already_imported
    assert snapshot(engine) == before


def test_import_adds_and_rejects(sessions: sessionmaker[Session], tmp_path: Path) -> None:
    base = default_dictionary_path().read_text(encoding="utf-8")
    added = _write(tmp_path, "d2.psv", base + "fastp.new_metric|bp|int|0..|New|A new metric\n")
    with sessions() as s, s.begin():
        result = import_dictionary(s, added, "test")
        assert result.added == ["fastp.new_metric"]
    removed = _write(tmp_path, "d3.psv", "\n".join(base.splitlines()[1:]) + "\n")
    unit = _write(
        tmp_path,
        "d4.psv",
        base.replace("fastp.read_length|bp|", "fastp.read_length|nt|")
        + "fastp.new_metric|bp|int|0..|New|A new metric\n",
    )
    for path, message in ((removed, "missing from the file"), (unit, "unit changed")):
        with sessions() as s, s.begin(), pytest.raises(DictionaryImportError, match=message):
            import_dictionary(s, path, "test")


def test_type_widening_and_narrowing(sessions: sessionmaker[Session], tmp_path: Path) -> None:
    base = default_dictionary_path().read_text(encoding="utf-8")
    widened = _write(
        tmp_path,
        "w.psv",
        base.replace(
            "fastp.n_" if False else "kraken2.n_fragments_total|fragments|int",
            "kraken2.n_fragments_total|fragments|float",
        ),
    )
    with sessions() as s, s.begin():
        result = import_dictionary(s, widened, "test")
        assert result.changed == ["kraken2.n_fragments_total"]
        assert (
            s.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.entity_id == "kraken2.n_fragments_total")
            )
            == 1
        )
    upstream = _write(tmp_path, "up.psv", SPEC.read_text(encoding="utf-8"))  # insert_size_peak int
    with sessions() as s, s.begin():
        result = import_dictionary(s, upstream, "test")
        assert any("fastp.insert_size_peak" in w and "float" in w for w in result.warnings)
        row = s.get(MetricDefinition, "fastp.insert_size_peak")
        assert row is not None and row.value_type == "float"


def test_label_import(sessions: sessionmaker[Session], tmp_path: Path) -> None:
    labels = _write(tmp_path, "pl.psv", "fastp.read_length|Długość odczytu (surowe)|\n")
    with sessions() as s, s.begin():
        result = import_labels(s, labels, "pl", "test")
        assert result.added == ["fastp.read_length"]
        row = s.get(MetricLabel, ("fastp.read_length", "pl"))
        assert row is not None and row.label == "Długość odczytu (surowe)"
    unknown = _write(tmp_path, "pl2.psv", "fastp.nope|X|\n")
    with sessions() as s, s.begin(), pytest.raises(DictionaryImportError):
        import_labels(s, unknown, "pl", "test")


def test_polish_labels_cover_the_dictionary(sessions: sessionmaker[Session]) -> None:
    labels = default_dictionary_path().with_name("metric_labels.pl.psv")
    keys = [line.split("|")[0] for line in labels.read_text(encoding="utf-8").splitlines()]
    dictionary = parse_dictionary(default_dictionary_path().read_text(encoding="utf-8"))
    assert keys == [s.key for s in dictionary]
    with sessions() as s, s.begin():
        result = import_labels(s, labels, "pl", "test")
        assert len(result.added) == 140

"""Stage 2 acceptance tests for ``qcdb load`` against real PostgreSQL."""

from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from qcdb.db.models import (
    AmrHit,
    MetricValue,
    OrderSample,
    QcCheck,
    ResultVersion,
    Run,
    RunMembership,
    Sample,
    SampleOrder,
    SampleRun,
    SourceDocument,
    SpeciesAbundance,
    ToolResult,
)
from qcdb.jsonio import loads_exact
from qcdb.summary_columns import SUMMARY_COLUMNS
from tests.conftest import FIXTURES, Loader, snapshot

RUN1 = FIXTURES / "RUN_2606"
RUN2 = FIXTURES / "RUN_2607"


def read(path: Path) -> Any:
    return loads_exact(path.read_bytes())


def write(path: Path, doc: Any) -> None:
    from qcdb.jsonio import dumps_exact

    path.write_text(dumps_exact(doc) + "\n", encoding="utf-8")


def current_version(session: Session, run_code: str, sample_code: str) -> ResultVersion | None:
    sr = session.scalar(
        select(SampleRun)
        .join(Run, Run.id == SampleRun.run_id)
        .where(Run.run_code == run_code, SampleRun.sample_code == sample_code)
    )
    if sr is None or sr.current_version_id is None:
        return None
    return session.get(ResultVersion, sr.current_version_id)


# ---------------------------------------------------------------------- clean load, idempotency
def test_clean_load(load: Loader, sessions: sessionmaker[Session]) -> None:
    report = load(RUN1)
    print("\n".join(report.lines()))
    assert report.exit_code == 0, report.lines()
    assert report.rejected == [] and report.unreadable == [] and report.warnings == []
    assert report.samples["new_version"] == 4  # 5156, 5157, 5158, 5160
    assert report.samples["no_results"] == 1  # 5159: report:false, no documents
    assert report.samples["incomplete"] == 1  # 5160: metrics only
    assert report.runs == {"RUN_2606"}
    with sessions() as s:
        verdicts = {
            code: (v.verdict if (v := current_version(s, "RUN_2606", code)) else "no version")
            for code in ("260630_5156", "260630_5157", "260630_5158", "260630_5159", "260630_5160")
        }
    assert verdicts == {
        "260630_5156": "PASS",
        "260630_5157": "WARN",
        "260630_5158": "FAIL",
        "260630_5159": "no version",
        "260630_5160": None,
    }


def test_second_load_changes_no_rows(load: Loader, engine: Engine) -> None:
    assert load(RUN1).exit_code == 0
    before = snapshot(engine)
    report = load(RUN1)
    assert report.exit_code == 0
    assert report.samples["new_version"] == 0
    assert report.samples["unchanged"] == 4
    assert snapshot(engine) == before


def test_dry_run_writes_nothing(load: Loader, engine: Engine) -> None:
    before = snapshot(engine)
    report = load(RUN1, dry_run=True)
    assert report.exit_code == 0
    assert report.samples["new_version"] == 4
    assert snapshot(engine) == before


# ---------------------------------------------------------------------- values
def test_every_metric_value_matches_input(load: Loader, sessions: sessionmaker[Session]) -> None:
    assert load(RUN1).exit_code == 0
    expected: dict[tuple[str, str], tuple[str, Any]] = {}
    for path in sorted(RUN1.glob("*.metrics.json")):
        doc = read(path)
        for name, metric in doc["metrics"].items():
            key = (doc["sample_id"], f"{doc['source']['tool']}.{name}")
            expected[key] = (metric["unit"], metric["value"])
    with sessions() as s:
        rows = s.execute(
            select(SampleRun.sample_code, MetricValue)
            .join(ResultVersion, ResultVersion.id == SampleRun.current_version_id)
            .join(ToolResult, ToolResult.version_id == ResultVersion.id)
            .join(MetricValue, MetricValue.tool_result_id == ToolResult.id)
        ).all()
    actual = {(code, mv.metric_key): mv for code, mv in rows}
    assert set(actual) == set(expected), "absent metrics must have no row, present ones a row"
    for key, (unit, value) in expected.items():
        mv = actual[key]
        assert mv.unit == unit, key
        stored = [x for x in (mv.value_num, mv.value_text, mv.value_bool) if x is not None]
        if value is None:
            assert stored == [], f"{key}: null must be stored without a value"
        elif isinstance(value, bool):
            assert mv.value_bool is value and len(stored) == 1, key
        elif isinstance(value, str):
            assert mv.value_text == value and len(stored) == 1, key
        else:
            assert isinstance(mv.value_num, Decimal), key
            assert mv.value_num == Decimal(str(value)), f"{key}: {mv.value_num} != {value}"
            assert len(stored) == 1, key


def test_all_statuses_and_absent_null_zero(load: Loader, sessions: sessionmaker[Session]) -> None:
    assert load(RUN1).exit_code == 0
    with sessions() as s:
        statuses = set(s.scalars(select(ToolResult.status)))
        assert statuses == {"ok", "empty", "skipped", "failed", "missing"}

        def metric(sample: str, key: str) -> MetricValue | None:
            return s.scalar(
                select(MetricValue)
                .join(ToolResult, ToolResult.id == MetricValue.tool_result_id)
                .join(SampleRun, SampleRun.current_version_id == ToolResult.version_id)
                .where(SampleRun.sample_code == sample, MetricValue.metric_key == key)
            )

        # conditional metrics: absent -> no row
        assert metric("260630_5157", "fastp.pct_duplication") is None
        assert metric("260630_5157", "seqkit.l50") is None
        assert metric("260630_5156", "fastp.pct_duplication") is not None
        # null -> row without value
        st = metric("260630_5157", "mlst.sequence_type")
        assert st is not None and (st.value_num, st.value_text, st.value_bool) == (None, None, None)
        # 0 -> numeric zero
        zero = metric("260630_5157", "amrfinder.n_amr_genes")
        assert zero is not None and zero.value_num == 0
        # text value that looks like a number stays text (trap 4)
        st19 = metric("260630_5156", "mlst.sequence_type")
        assert st19 is not None and st19.value_text == "19" and st19.value_num is None
        # contamination above 100 is stored (trap 6)
        c2 = metric("260630_5158", "checkm2.pct_contamination")
        c1 = metric("260630_5158", "checkm.pct_contamination")
        assert c2 is not None and c2.value_num == Decimal("112.5")
        assert c1 is not None and c1.value_num == Decimal("145.3")
        # messages: key present but empty vs. non-empty
        ectyper = s.scalar(
            select(ToolResult)
            .join(SampleRun, SampleRun.current_version_id == ToolResult.version_id)
            .where(SampleRun.sample_code == "260630_5156", ToolResult.tool == "ectyper")
        )
        assert ectyper is not None and ectyper.status == "skipped" and ectyper.messages
        assert ectyper.data == {}


def test_qc_checks_and_thresholds_stored_verbatim(
    load: Loader, sessions: sessionmaker[Session]
) -> None:
    assert load(RUN1).exit_code == 0
    qc = read(RUN1 / "260630_5157.qc.json")
    with sessions() as s:
        v = current_version(s, "RUN_2606", "260630_5157")
        assert v is not None
        assert v.verdict == qc["verdict"] == "WARN"
        th = qc["thresholds"]
        assert (
            v.thresholds_sha256,
            v.profile,
            v.read_length_profile,
            v.threshold_species,
            v.threshold_chain,
            v.thresholds_file,
        ) == (
            th["sha256"],
            th["profile"],
            th["read_length_profile"],
            th["species"],
            th["chain"],
            th["file"],
        )
        checks = s.scalars(
            select(QcCheck).where(QcCheck.version_id == v.id).order_by(QcCheck.ordinal)
        ).all()
        assert len(checks) == len(qc["checks"])
        for row, c in zip(checks, qc["checks"], strict=True):
            value = row.value_text if row.value_text is not None else row.value_num
            assert (row.metric, row.unit, row.rule, row.required, row.status, row.reason) == (
                c["metric"],
                c["unit"],
                c["rule"],
                c["required"],
                c["status"],
                c["reason"],
            )
            assert value == c["value"]
        assert {c.metric for c in checks} >= {"species_match", "derived.depth"}  # no FK (trap 8)


def test_child_tables(load: Loader, sessions: sessionmaker[Session]) -> None:
    assert load(RUN1).exit_code == 0
    with sessions() as s:
        hits = s.scalars(select(AmrHit).order_by(AmrHit.ordinal)).all()
        assert [h.symbol for h in hits][:2] == ["blaTEM-1", "aph(3'')-Ib"]
        assert hits[0].start_pos == 101201 and hits[0].pct_identity == Decimal("100.0")
        assert {h.type for h in hits} == {"AMR", "STRESS", "VIRULENCE"}
        abundances = s.scalars(select(SpeciesAbundance)).all()
        assert {a.name for a in abundances} >= {"Salmonella enterica", "Escherichia coli"}


def test_summary_view_matches_run_document(load: Loader, engine: Engine) -> None:
    assert load(RUN1).exit_code == 0
    run_doc = read(RUN1 / "RUN_2606.run.json")
    with engine.connect() as conn:
        rows = {
            r["sample_code"]: r
            for r in conn.execute(text("SELECT * FROM sample_run_summary")).mappings()
        }
    assert set(rows) == {s["sample_id"] for s in run_doc["samples"]}
    for entry in run_doc["samples"]:
        row = rows[entry["sample_id"]]
        assert row["verdict"] == entry["verdict"]
        for col in SUMMARY_COLUMNS:
            if col.id in entry["values"]:
                assert row[col.id] == entry["values"][col.id], (entry["sample_id"], col.id)
    # the brief's example row (reads = pairs x 2)
    r = rows["260630_5156"]
    assert (
        r["raw_reads"],
        r["reads"],
        r["depth"],
        r["species"],
        r["mlst_st"],
        r["serotype"],
        r["n_amr_genes"],
    ) == (2857664, 2796746, Decimal("74.9057"), "Salmonella enterica", "19", "Typhimurium", 4)
    assert rows["260630_5159"]["has_results"] is False
    assert rows["260630_5160"]["has_results"] is True and rows["260630_5160"]["verdict"] is None


# ---------------------------------------------------------------------- runs, membership
def test_sample_in_two_runs(load: Loader, sessions: sessionmaker[Session]) -> None:
    assert load(RUN1).exit_code == 0
    report = load(RUN2)
    assert report.exit_code == 0, report.lines()
    assert report.runs == {"RUN_2607"}
    with sessions() as s:
        results = s.scalars(select(SampleRun).where(SampleRun.sample_code == "260630_5156")).all()
        assert len(results) == 2
        assert len({r.run_id for r in results}) == 2
        assert len({r.sample_id for r in results}) == 1  # auto-linked to one biological sample
        v1 = current_version(s, "RUN_2606", "260630_5156")
        v2 = current_version(s, "RUN_2607", "260630_5156")
        assert v1 is not None and v2 is not None
        assert v1.thresholds_sha256 != v2.thresholds_sha256
        sources = set(
            s.scalars(
                select(RunMembership.source)
                .join(Run, Run.id == RunMembership.run_id)
                .where(Run.run_code == "RUN_2607")
            )
        )
        assert sources == {"report"}


def test_membership_sources_recorded(load: Loader, sessions: sessionmaker[Session]) -> None:
    assert load(RUN1).exit_code == 0
    with sessions() as s:
        rows = s.execute(select(RunMembership.sample_code, RunMembership.source)).all()
    by_sample: dict[str, set[str]] = {}
    for code, source in rows:
        by_sample.setdefault(code, set()).add(source)
    assert by_sample["260630_5156"] == {"report", "run_json", "samplesheet"}
    assert by_sample["260630_5159"] == {"run_json", "samplesheet"}


def test_run_id_conflict_rejects_sample(
    load: Loader, run_dir: Path, sessions: sessionmaker[Session]
) -> None:
    report_path = run_dir / "260630_5157.report.json"
    doc = read(report_path)
    doc["run_id"] = "RUN_9999"
    write(report_path, doc)
    report = load(run_dir)
    assert report.exit_code == 1
    assert any(
        "260630_5157" in r and "conflicting run_id" in r and "RUN_9999" in r
        for r in report.rejected
    )
    with sessions() as s:
        assert s.scalar(select(SampleRun).where(SampleRun.sample_code == "260630_5157")) is None
        assert s.scalar(select(func.count()).select_from(SampleRun)) == 4


def test_run_id_missing_rejects_sample(load: Loader, tmp_path: Path) -> None:
    d = tmp_path / "only_metrics"
    d.mkdir()
    shutil.copy(RUN1 / "260630_5160.fastp.metrics.json", d)
    report = load(d)
    assert report.exit_code == 1
    assert "cannot determine run_id" in report.rejected[0]
    report = load(d, run_id="RUN_CLI")
    assert report.exit_code == 0 and report.runs == {"RUN_CLI"}


def test_cli_run_id_conflicting_with_run_document(load: Loader) -> None:
    report = load(RUN1, run_id="OTHER")
    assert report.exit_code == 1
    assert any("conflicts with --run-id" in r for r in report.rejected)


def test_run_date(load: Loader, sessions: sessionmaker[Session]) -> None:
    import datetime as dt

    assert load(RUN1, run_date=dt.date(2026, 6, 30)).exit_code == 0
    with sessions() as s:
        run = s.scalar(select(Run).where(Run.run_code == "RUN_2606"))
        assert run is not None and run.run_date == dt.date(2026, 6, 30)
        assert run.run_date_source == "cli"
    report = load(RUN1, run_date=dt.date(2026, 7, 1))
    assert report.exit_code == 2 and "already has date" in (report.usage_error or "")


def test_run_date_needs_single_run(load: Loader, tmp_path: Path) -> None:
    import datetime as dt

    d = tmp_path / "two"
    shutil.copytree(RUN1, d / "a")
    shutil.copytree(RUN2, d / "b")  # second run, sample renamed so both load
    for f in (d / "b").glob("260630_5156.*"):
        f.rename(f.with_name(f.name.replace("260630_5156", "260707_5201")))
    for f in (d / "b").glob("260707_5201.*.json"):
        doc = read(f)
        doc["sample_id"] = "260707_5201"
        write(f, doc)
    report = load(d, run_date=dt.date(2026, 6, 30))
    assert report.exit_code == 2 and "exactly one run" in (report.usage_error or "")


# ---------------------------------------------------------------------- invalid input
def test_invalid_document_leaves_no_partial_data(
    load: Loader, run_dir: Path, sessions: sessionmaker[Session]
) -> None:
    path = run_dir / "260630_5157.seqkit.metrics.json"
    doc = read(path)
    doc["metrics"]["n_contigs"]["unit"] = "sequences"
    write(path, doc)
    report = load(run_dir)
    assert report.exit_code == 1
    assert any(str(path) in r and "unit 'sequences'" in r for r in report.rejected)
    assert any("sample '260630_5157'" in r for r in report.rejected)
    with sessions() as s:
        assert s.scalar(select(SampleRun).where(SampleRun.sample_code == "260630_5157")) is None
        names = set(s.scalars(select(SourceDocument.file_name)))
        assert not any(n.startswith("260630_5157") for n in names)
        assert s.scalar(select(func.count()).select_from(ResultVersion)) == 3


def test_database_failure_mid_sample_rolls_back(
    load: Loader, sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from qcdb.loader import core

    original = core.Loader._tool_result

    def failing(self: core.Loader, doc: Any) -> ToolResult:
        if doc.content["sample_id"] == "260630_5158" and doc.content["source"]["tool"] == "mlst":
            from sqlalchemy.exc import IntegrityError

            raise IntegrityError("simulated", {}, Exception("simulated failure"))
        return original(self, doc)

    monkeypatch.setattr(core.Loader, "_tool_result", failing)
    report = load(RUN1)
    assert report.exit_code == 1
    with sessions() as s:
        assert s.scalar(select(SampleRun).where(SampleRun.sample_code == "260630_5158")) is None
        assert not any(
            n.startswith("260630_5158") for n in s.scalars(select(SourceDocument.file_name))
        )
        assert current_version(s, "RUN_2606", "260630_5156") is not None


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda d: d["metrics"].update({"new_metric": {"value": 1, "unit": "x"}}),
            "qcdb import-dictionary",
        ),
        (lambda d: d["metrics"]["insert_size_peak"].update({"value": 252.5}), None),
        (
            lambda d: d["metrics"]["read_pairs_after_filter"].update({"value": Decimal("1.5")}),
            "is not of dictionary type int",
        ),
        (
            lambda d: d["metrics"]["read_pairs_after_filter"].update({"value": True}),
            "is not of dictionary type int",
        ),
        (
            lambda d: d["metrics"]["pct_q30_after_filter"].update({"value": Decimal("100.5")}),
            "above the dictionary range",
        ),
        (
            lambda d: d["metrics"]["pct_q30_after_filter"].update({"value": None}),
            "value is null but the document has no messages",
        ),
        (lambda d: d.update({"schema_version": "2.0"}), 'unsupported schema_version "2.0"'),
        (lambda d: d.update({"status": "failed"}), "/metrics"),
        (lambda d: d.update({"namespace": "assembly"}), "does not match tool 'fastp'"),
        (lambda d: d.update({"extra": 1}), "Additional properties"),
    ],
)
def test_metric_validation(load: Loader, run_dir: Path, mutate: Any, message: str | None) -> None:
    path = run_dir / "260630_5156.fastp.metrics.json"
    doc = read(path)
    mutate(doc)
    write(path, doc)
    report = load(run_dir)
    if message is None:  # fastp.insert_size_peak is float in qcdb's dictionary (D4)
        assert report.exit_code == 0, report.lines()
        return
    assert report.exit_code == 1, report.lines()
    assert any(message in r for r in report.rejected), report.rejected


def test_int_metric_accepts_whole_decimal(
    load: Loader, run_dir: Path, sessions: sessionmaker[Session]
) -> None:
    path = run_dir / "260630_5156.fastp.metrics.json"
    doc = read(path)
    doc["metrics"]["read_pairs_after_filter"]["value"] = Decimal("1398373.0")
    write(path, doc)
    assert load(run_dir).exit_code == 0
    with sessions() as s:
        value = s.scalar(
            select(MetricValue.value_num)
            .where(MetricValue.metric_key == "fastp.read_pairs_after_filter")
            .order_by(MetricValue.id)
            .limit(1)
        )
    assert value == Decimal("1398373.0") and str(value) == "1398373.0"  # stored as given


def test_invalid_qc_document(load: Loader, run_dir: Path) -> None:
    path = run_dir / "260630_5156.qc.json"
    doc = read(path)
    doc["checks"][1]["reason"] = "should be null for PASS"
    write(path, doc)
    report = load(run_dir)
    assert report.exit_code == 1
    assert any("260630_5156.qc.json" in r for r in report.rejected)


def test_unreadable_file(load: Loader, run_dir: Path, sessions: sessionmaker[Session]) -> None:
    (run_dir / "260630_5157.bracken.metrics.json").write_text("{not json", encoding="utf-8")
    report = load(run_dir)
    assert report.exit_code == 3, report.lines()
    assert "invalid JSON" in report.unreadable[0]
    with sessions() as s:
        assert s.scalar(select(SampleRun).where(SampleRun.sample_code == "260630_5157")) is None
        assert current_version(s, "RUN_2606", "260630_5156") is not None


def test_validation_failure_takes_precedence_over_unreadable(load: Loader, run_dir: Path) -> None:
    (run_dir / "260630_5157.bracken.metrics.json").write_text("{not json", encoding="utf-8")
    path = run_dir / "260630_5156.fastp.metrics.json"
    doc = read(path)
    doc["metrics"]["read_length"]["unit"] = "nt"
    write(path, doc)
    assert load(run_dir).exit_code == 1  # D6: 2 > 1 > 3


def test_usage_errors(load: Loader, tmp_path: Path) -> None:
    assert load(tmp_path / "missing").exit_code == 2
    assert load(RUN1, metadata=tmp_path / "nope.csv").exit_code == 2


# ---------------------------------------------------------------------- reprocessing
def test_reprocessing_creates_versions(
    load: Loader, run_dir: Path, sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    original = tmp_path / "original"
    shutil.copytree(run_dir, original)
    assert load(run_dir).exit_code == 0
    path = run_dir / "260630_5157.qc.json"
    doc = read(path)
    doc["verdict"] = "FAIL"
    doc["checks"][1].update({"status": "FAIL", "reason": "81 < 85 (min, reprocessed)"})
    write(path, doc)
    report = load(run_dir)
    assert report.exit_code == 0 and report.samples["new_version"] == 1
    with sessions() as s:
        versions = s.scalars(
            select(ResultVersion)
            .join(SampleRun, SampleRun.id == ResultVersion.sample_run_id)
            .where(SampleRun.sample_code == "260630_5157")
            .order_by(ResultVersion.version_no)
        ).all()
        assert [(v.version_no, v.verdict) for v in versions] == [(1, "WARN"), (2, "FAIL")]
        current = current_version(s, "RUN_2606", "260630_5157")
        assert current is not None and current.version_no == 2
    # loading the original directory again matches version 1: nothing changes
    report = load(original)
    assert report.samples["new_version"] == 0
    with sessions() as s:
        current = current_version(s, "RUN_2606", "260630_5157")
        assert current is not None and current.version_no == 2


def test_qc_input_hash_mismatch_is_a_warning(
    load: Loader, run_dir: Path, sessions: sessionmaker[Session]
) -> None:
    path = run_dir / "260630_5156.checkm2.metrics.json"
    doc = read(path)
    doc["metrics"]["pct_completeness"]["value"] = Decimal("99.88")
    write(path, doc)
    report = load(run_dir)
    assert report.exit_code == 0
    assert any(
        "does not match loaded 260630_5156.checkm2.metrics.json" in w for w in report.warnings
    )
    with sessions() as s:
        v = current_version(s, "RUN_2606", "260630_5156")
        assert v is not None and any("sha256" in w for w in v.load_warnings)


def test_missing_qc_and_report_marks_incomplete(
    load: Loader, run_dir: Path, sessions: sessionmaker[Session]
) -> None:
    (run_dir / "260630_5158.report.json").unlink()
    report = load(run_dir)
    assert report.exit_code == 0
    assert report.samples["incomplete"] == 2
    assert any("report=True but report.json absent" in w for w in report.warnings)
    with sessions() as s:
        v = current_version(s, "RUN_2606", "260630_5158")
        assert v is not None and v.has_qc and not v.has_report and v.verdict == "FAIL"


# ---------------------------------------------------------------------- orders and metadata
def test_order_import(load: Loader, sessions: sessionmaker[Session], engine: Engine) -> None:
    assert load(RUN1).exit_code == 0
    report = load(FIXTURES / "orders")
    assert report.exit_code == 0, report.lines()
    with sessions() as s:
        order = s.scalar(select(SampleOrder).where(SampleOrder.order_code == "ZL/2026/001"))
        assert order is not None and order.owner_id is None  # owners are never auto-created
        assert order.meta == {"Zleceniodawca": "Jan Kowalski"}
        linked = set(
            s.scalars(
                select(Sample.sample_code)
                .join(OrderSample, OrderSample.sample_id == Sample.id)
                .where(OrderSample.order_id == order.id)
            )
        )
        assert linked == {"260630_5156", "260630_5157"}
    before = snapshot(engine)
    assert load(FIXTURES / "orders").exit_code == 0
    assert snapshot(engine) == before


def test_order_before_results_warns(load: Loader) -> None:
    report = load(FIXTURES / "orders")
    assert report.exit_code == 0
    assert any("is not in the database" in w for w in report.warnings)


def test_metadata_import(load: Loader, sessions: sessionmaker[Session], engine: Engine) -> None:
    import datetime as dt

    assert load(RUN1).exit_code == 0
    metadata = FIXTURES / "metadata" / "metadata.csv"
    report = load(FIXTURES / "metadata", metadata=metadata)
    assert report.exit_code == 0, report.lines()
    with sessions() as s:
        run = s.scalar(select(Run).where(Run.run_code == "RUN_2606"))
        assert run is not None and run.run_date == dt.date(2026, 6, 30)
        assert run.run_date_source == "metadata"
        sample = s.scalar(select(Sample).where(Sample.sample_code == "260630_5156"))
        assert sample is not None
        assert sample.metadata_ == {
            "material_type": "izolat",
            "collection_site": "Zakład Przykładowy",
            "collection_date": "2026-06-20",
            "expected_species": "Salmonella enterica",
        }
        orders = set(s.scalars(select(SampleOrder.order_code)))
        assert orders == {"ZL/2026/001", "ZL/2026/002"}
    before = snapshot(engine)
    assert load(FIXTURES / "metadata", metadata=metadata).exit_code == 0
    assert snapshot(engine) == before


def test_metadata_rejects_bad_rows(load: Loader, tmp_path: Path) -> None:
    assert load(RUN1).exit_code == 0
    bad = tmp_path / "meta.csv"
    bad.write_text(
        "sample_id,run_id,collection_date\n260630_5156,RUN_2606,30.06.2026\n", encoding="utf-8"
    )
    report = load(tmp_path, metadata=bad)
    assert report.exit_code == 1
    assert "not a date" in report.rejected[0]
    unknown = tmp_path / "meta2.csv"
    unknown.write_text("sample_id,pesel\n260630_5156,1\n", encoding="utf-8")
    report = load(tmp_path, metadata=unknown)
    assert report.exit_code == 1 and "unknown column(s): pesel" in report.rejected[0]


def test_report_meta_kept_verbatim(load: Loader, sessions: sessionmaker[Session]) -> None:
    assert load(RUN1).exit_code == 0
    with sessions() as s:
        v7 = current_version(s, "RUN_2606", "260630_5157")
        v6 = current_version(s, "RUN_2606", "260630_5156")
        assert v7 is not None and v6 is not None
        assert v7.meta == {"run_id": "RUN_2606", "Zleceniodawca": "Jan Kowalski"}
        assert v6.meta is not None and v6.meta["zleceniodawca"] == "Jan Kowalski"
        from qcdb.db.models import Owner

        assert s.scalar(select(func.count()).select_from(Owner)) == 0


def test_source_documents_keep_exact_numbers(load: Loader, engine: Engine) -> None:
    assert load(RUN1).exit_code == 0
    with engine.connect() as conn:
        raw = conn.execute(
            text(
                "SELECT content->'metrics'->'read_length'->>'value' FROM source_document "
                "WHERE file_name = '260630_5156.fastp.metrics.json'"
            )
        ).scalar_one()
    assert raw == "151.0"
    doc = json.loads((RUN1 / "260630_5156.fastp.metrics.json").read_text())
    assert doc["metrics"]["read_length"]["value"] == 151.0

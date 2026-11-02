"""``qcdb load``: validate, resolve run_id, and write one transaction per (run_id, sample_id)."""

from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import os
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from qcdb import __version__
from qcdb.db.models import (
    AmrHit,
    AuditLog,
    LoadBatch,
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
from qcdb.dictionary import load_dictionary
from qcdb.loader.scan import PER_SAMPLE_KINDS, Document, Samplesheet, sample_hint, scan
from qcdb.loader.validate import check_schema_version, metric_errors, schema_errors
from qcdb.summary_columns import summary_values


class LoadError(Exception):
    """A problem that rejects one unit of work (a sample, a run or an order)."""


class UsageError(Exception):
    """A problem with the invocation; nothing is loaded."""


@dataclass
class LoadOptions:
    directory: Path
    run_id: str | None = None
    run_date: dt.date | None = None
    metadata: Path | None = None
    dry_run: bool = False
    invoked_by: str = field(
        default_factory=lambda: os.environ.get("QCDB_INVOKED_BY") or getpass.getuser()
    )


@dataclass
class LoadReport:
    dry_run: bool = False
    documents: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    samples: Counter[str] = field(default_factory=Counter)
    rejected: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    usage_error: str | None = None
    ignored_files: int = 0
    runs: set[str] = field(default_factory=set)

    @property
    def exit_code(self) -> int:
        """D6: usage error 2, otherwise any rejection 1, otherwise unreadable input 3."""
        if self.usage_error:
            return 2
        if self.rejected:
            return 1
        if self.unreadable:
            return 3
        return 0

    def lines(self) -> list[str]:
        if self.usage_error:
            return [f"usage error: {self.usage_error}"]
        out = [f"qcdb load{' (dry run, nothing written)' if self.dry_run else ''}"]
        for kind in ("metrics", "qc", "report", "run", "order", "metadata"):
            c = self.documents.get(kind)
            if c:
                out.append(
                    f"  {kind:<8} loaded {c['loaded']}, identical {c['identical']}, "
                    f"rejected {c['rejected']}, skipped {c['skipped']}"
                )
        s = self.samples
        out.append(
            f"  samples  new versions {s['new_version']}, unchanged {s['unchanged']}, "
            f"rejected {s['rejected']}, skipped {s['skipped']}, incomplete {s['incomplete']}, "
            f"listed without results {s['no_results']}"
        )
        out.append(f"  runs     {', '.join(sorted(self.runs)) or '-'}")
        out.append(f"  ignored files {self.ignored_files}")
        out += [f"UNREADABLE {m}" for m in self.unreadable]
        out += [f"REJECT {m}" for m in self.rejected]
        out += [f"WARN {m}" for m in self.warnings]
        return out


@dataclass
class Bundle:
    """All valid per-sample documents for one sample_id in this load."""

    sample_id: str
    metrics: dict[str, Document] = field(default_factory=dict)
    qc: Document | None = None
    report: Document | None = None
    problems: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def documents(self) -> list[Document]:
        docs = list(self.metrics.values())
        docs += [d for d in (self.qc, self.report) if d is not None]
        return docs

    def fingerprint(self) -> str:
        lines = sorted(
            f"{d.kind}:{d.content['source']['tool'] if d.kind == 'metrics' else ''}:{d.sha256}"
            for d in self.documents()
        )
        return hashlib.sha256("\n".join(lines).encode()).hexdigest()


@dataclass
class Membership:
    run_code: str
    source: str  # report | run_json | samplesheet | cli
    label: str
    sha256: str | None
    entry: dict[str, Any] | None = None


def _split_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, bool):
        return {"value_bool": value}
    if isinstance(value, (int, Decimal)):
        return {"value_num": value}
    return {"value_text": str(value)}


def _num(value: Any) -> int | Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return None
    return value


def _int(value: Any) -> int | None:
    n = _num(value)
    if n is None or n != int(n):
        return None
    return int(n)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


class Loader:
    def __init__(self, session: Session, options: LoadOptions) -> None:
        self.session = session
        self.opts = options
        self.report = LoadReport(dry_run=options.dry_run)
        self.batch_id: int | None = None
        self.started = dt.datetime.now(dt.timezone.utc)
        self.actor = f"loader:{options.invoked_by}"
        self._date_run: str | None = None

    # ------------------------------------------------------------------ transactions
    @contextmanager
    def _unit(self) -> Iterator[None]:
        batch_before = self.batch_id
        try:
            if self.opts.dry_run:
                with self.session.begin_nested():
                    yield
            else:
                with self.session.begin():
                    yield
        except BaseException:
            self.batch_id = batch_before
            raise

    def _batch(self) -> int:
        if self.batch_id is None:
            batch = LoadBatch(
                started_at=self.started,
                invoked_by=self.opts.invoked_by,
                qcdb_version=__version__,
                source_dir=str(self.opts.directory.resolve()),
                options={
                    "run_id": self.opts.run_id,
                    "run_date": self.opts.run_date.isoformat() if self.opts.run_date else None,
                    "metadata": self.opts.metadata.name if self.opts.metadata else None,
                },
            )
            self.session.add(batch)
            self.session.flush()
            self.batch_id = batch.id
        return self.batch_id

    def _audit(self, action: str, entity_type: str, entity_id: object, changes: Any) -> None:
        self.session.add(
            AuditLog(
                actor_label=self.actor,
                load_batch_id=self._batch(),
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id),
                changes=changes,
            )
        )

    # ------------------------------------------------------------------ entry point
    def run(self) -> LoadReport:
        directory = self.opts.directory
        if not directory.is_dir():
            self.report.usage_error = f"not a directory: {directory}"
            return self.report
        if self.opts.metadata is not None and not self.opts.metadata.is_file():
            self.report.usage_error = f"metadata file not found: {self.opts.metadata}"
            return self.report
        outer = self.session.begin() if self.opts.dry_run else None
        try:
            self._run()
        except UsageError as exc:
            self.report.usage_error = str(exc)
        finally:
            if outer is not None:
                outer.rollback()
            elif self.session.in_transaction():
                self.session.rollback()
        return self.report

    def _run(self) -> None:
        with self._read():
            dictionary = load_dictionary(self.session)
        if not dictionary:
            raise UsageError("the metric dictionary is empty; run 'qcdb import-dictionary' first")
        found = scan(self.opts.directory)
        self.report.ignored_files = found.ignored
        for item in found.unreadable:
            self.report.unreadable.append(f"{item.path}: {item.message}")

        valid: list[Document] = []
        rejected_samples: dict[str, list[str]] = defaultdict(list)
        for doc in found.documents:
            errors = self._validate(doc, dictionary)
            if errors:
                self._reject_doc(doc, "; ".join(errors))
                sid = doc.content.get("sample_id") if isinstance(doc.content, dict) else None
                hint = sid if isinstance(sid, str) and sid else None
                if doc.kind in PER_SAMPLE_KINDS:
                    hint = hint or sample_hint(doc.name, doc.kind)
                    if hint:
                        rejected_samples[hint].append(doc.name)
            else:
                valid.append(doc)

        bundles = self._bundle(valid)
        for sid, names in rejected_samples.items():
            bundles.setdefault(sid, Bundle(sid)).problems.append(
                f"invalid document(s): {', '.join(names)}"
            )
        for item in found.unreadable:
            if item.sample_hint:
                bundles.setdefault(item.sample_hint, Bundle(item.sample_hint)).blocked_by.append(
                    item.path.name
                )

        run_docs = [d for d in valid if d.kind == "run"]
        order_docs = [d for d in valid if d.kind == "order"]
        run_docs = self._check_run_docs(run_docs)
        memberships = self._memberships(bundles, run_docs, found.samplesheets)
        keys = self._resolve(bundles, memberships)
        self._check_run_date(keys, run_docs)

        for doc in run_docs:
            self._load_run_doc(doc)
        run_entries = {
            (d.content["run_id"], s["sample_id"]): s for d in run_docs for s in d.content["samples"]
        }
        for (run_code, sample_code), (bundle, sources) in sorted(keys.items()):
            self._load_key(
                run_code, sample_code, bundle, sources, run_entries.get((run_code, sample_code))
            )
        if self.opts.run_date is not None:
            self._apply_run_date()
        for doc in order_docs:
            self._load_order_doc(doc)
        if self.opts.metadata is not None:
            from qcdb.loader.metadata import apply_metadata

            apply_metadata(self, self.opts.metadata)
        self._check_run_summaries(run_docs)
        self._finish()

    @contextmanager
    def _read(self) -> Iterator[None]:
        if self.opts.dry_run:
            with self.session.begin_nested():
                yield
        else:
            with self.session.begin():
                yield

    # ------------------------------------------------------------------ validation
    def _validate(self, doc: Document, dictionary: dict[str, Any]) -> list[str]:
        error = check_schema_version(doc.content)
        if error:
            return [error]
        errors = schema_errors(doc.kind, doc.content)
        if not errors and doc.kind == "metrics":
            errors = metric_errors(doc.content, dictionary)
        return errors

    def _reject_doc(self, doc: Document, message: str) -> None:
        self.report.rejected.append(f"{doc.path}: {message}")
        self.report.documents[doc.kind]["rejected"] += 1

    def _bundle(self, docs: list[Document]) -> dict[str, Bundle]:
        bundles: dict[str, Bundle] = {}
        for doc in docs:
            if doc.kind not in PER_SAMPLE_KINDS:
                continue
            sid: str = doc.content["sample_id"]
            bundle = bundles.setdefault(sid, Bundle(sid))
            if doc.kind == "metrics":
                tool = doc.content["source"]["tool"]
                expected = f"{sid}.{tool}.metrics.json"
                if tool in bundle.metrics:
                    bundle.problems.append(
                        f"two different {tool} documents "
                        f"({bundle.metrics[tool].name}, {doc.name}); "
                        "load run directories separately"
                    )
                bundle.metrics[tool] = doc
            else:
                expected = f"{sid}.{doc.kind}.json"
                if getattr(bundle, doc.kind) is not None:
                    bundle.problems.append(
                        f"two different {doc.kind}.json documents; load run directories separately"
                    )
                setattr(bundle, doc.kind, doc)
            if doc.name != expected:
                bundle.warnings.append(
                    f"{doc.path}: file name does not match its content (expected {expected})"
                )
        for bundle in bundles.values():
            self._check_qc_inputs(bundle)
        return bundles

    def _check_qc_inputs(self, bundle: Bundle) -> None:
        if bundle.qc is None:
            return
        for item in bundle.qc.content["inputs"]:
            doc = bundle.metrics.get(item["tool"])
            if doc is None:
                bundle.warnings.append(
                    f"{bundle.qc.path}: input {item['path']} ({item['tool']}) was used by qceval "
                    "but is not among the loaded documents"
                )
            elif doc.sha256 != item["sha256"]:
                bundle.warnings.append(
                    f"{bundle.qc.path}: sha256 of input {item['path']} ({item['sha256'][:12]}…) "
                    f"does not match loaded {doc.name} ({doc.sha256[:12]}…)"
                )

    def _check_run_docs(self, run_docs: list[Document]) -> list[Document]:
        by_code: dict[str, list[Document]] = defaultdict(list)
        for doc in run_docs:
            by_code[doc.content["run_id"]].append(doc)
        accepted: list[Document] = []
        for code, docs in by_code.items():
            if len(docs) > 1:
                for doc in docs:
                    self._reject_doc(doc, f"several different run documents for run {code!r}")
                continue
            doc = docs[0]
            if self.opts.run_id is not None and code != self.opts.run_id:
                self._reject_doc(
                    doc, f"run_id {code!r} conflicts with --run-id {self.opts.run_id!r}"
                )
                continue
            accepted.append(doc)
        return accepted

    # ------------------------------------------------------------------ run_id resolution
    def _memberships(
        self, bundles: dict[str, Bundle], run_docs: list[Document], sheets: list[Samplesheet]
    ) -> dict[str, list[Membership]]:
        """Every source that says which run a sample belongs to (trap 1)."""
        result: dict[str, list[Membership]] = defaultdict(list)
        for sid, bundle in bundles.items():
            if bundle.report is not None and bundle.report.content["run_id"] is not None:
                result[sid].append(
                    Membership(
                        bundle.report.content["run_id"],
                        "report",
                        f"report.json {bundle.report.name}",
                        bundle.report.sha256,
                    )
                )
        for doc in run_docs:
            for entry in doc.content["samples"]:
                result[entry["sample_id"]].append(
                    Membership(
                        doc.content["run_id"], "run_json", f"run.json {doc.name}", doc.sha256, entry
                    )
                )
        for sheet in sheets:
            for row in sheet.rows:
                if row.run_id is not None:
                    result[row.sample_id].append(
                        Membership(
                            row.run_id,
                            "samplesheet",
                            f"samplesheet {sheet.path.name}",
                            sheet.sha256,
                        )
                    )
                elif self.opts.run_id is None:
                    result.setdefault(row.sample_id, [])
        if self.opts.run_id is not None:
            listed = set(bundles) | {r.sample_id for s in sheets for r in s.rows}
            for sid in listed:
                result[sid].append(Membership(self.opts.run_id, "cli", "--run-id", None))
        return result

    def _resolve(
        self, bundles: dict[str, Bundle], memberships: dict[str, list[Membership]]
    ) -> dict[tuple[str, str], tuple[Bundle | None, list[Membership]]]:
        keys: dict[tuple[str, str], tuple[Bundle | None, list[Membership]]] = {}
        for sid, bundle in bundles.items():
            sources = memberships.get(sid, [])
            codes = {m.run_code for m in sources}
            if bundle.blocked_by:
                self._skip(bundle, f"unreadable file(s): {', '.join(bundle.blocked_by)}")
                continue
            if bundle.problems:
                self._reject_bundle(bundle, "; ".join(bundle.problems))
                continue
            if not codes:
                self._reject_bundle(
                    bundle,
                    "cannot determine run_id: no run_id in report.json, not listed in any "
                    "run.json, no run_id in a samplesheet, and no --run-id given",
                )
                continue
            if len(codes) > 1:
                detail = "; ".join(f"{m.label} says {m.run_code!r}" for m in sources)
                self._reject_bundle(bundle, f"conflicting run_id: {detail}")
                continue
            self.report.warnings += bundle.warnings
            keys[(codes.pop(), sid)] = (bundle, sources)
        for sid, sources in memberships.items():
            if sid in bundles:
                continue
            if not sources:
                self.report.warnings.append(
                    f"samplesheet sample {sid!r} has no run_id and no --run-id was given; ignored"
                )
                continue
            by_code: dict[str, list[Membership]] = defaultdict(list)
            for m in sources:
                by_code[m.run_code].append(m)
            for code, items in by_code.items():
                keys[(code, sid)] = (None, items)
        return keys

    def _reject_bundle(self, bundle: Bundle, message: str) -> None:
        names = ", ".join(d.name for d in bundle.documents()) or "(no valid documents)"
        self.report.rejected.append(f"sample {bundle.sample_id!r} [{names}]: {message}")
        self.report.samples["rejected"] += 1
        for doc in bundle.documents():
            self.report.documents[doc.kind]["rejected"] += 1

    def _skip(self, bundle: Bundle, message: str) -> None:
        self.report.warnings.append(f"sample {bundle.sample_id!r} not loaded: {message}")
        self.report.samples["skipped"] += 1
        for doc in bundle.documents():
            self.report.documents[doc.kind]["skipped"] += 1

    def _check_run_date(
        self,
        keys: dict[tuple[str, str], tuple[Bundle | None, list[Membership]]],
        run_docs: list[Document],
    ) -> None:
        if self.opts.run_date is None:
            return
        codes = {code for code, _ in keys} | {d.content["run_id"] for d in run_docs}
        if len(codes) != 1:
            raise UsageError(
                f"--run-date needs exactly one run in the load, found {len(codes)}: "
                f"{', '.join(sorted(codes)) or '-'}"
            )
        code = next(iter(codes))
        with self._read():
            existing = self.session.scalar(select(Run).where(Run.run_code == code))
            if (
                existing is not None
                and existing.run_date is not None
                and existing.run_date != self.opts.run_date
            ):
                raise UsageError(
                    f"run {code!r} already has date {existing.run_date.isoformat()}; "
                    "change it in the web application"
                )
        self._date_run = code

    def _apply_run_date(self) -> None:
        if self._date_run is None:
            return
        with self._unit():
            run = self._get_run(self._date_run)
            if run.run_date is None:
                assert self.opts.run_date is not None
                run.run_date, run.run_date_source = self.opts.run_date, "cli"
                self._audit(
                    "update",
                    "run",
                    run.run_code,
                    {"run_date": {"old": None, "new": self.opts.run_date.isoformat()}},
                )

    # ------------------------------------------------------------------ writes
    def _get_run(self, code: str) -> Run:
        self.report.runs.add(code)
        run = self.session.scalar(select(Run).where(Run.run_code == code))
        if run is None:
            run = Run(run_code=code)
            self.session.add(run)
            self.session.flush()
            self._audit("create", "run", code, {})
        return run

    def _source_document(self, doc: Document) -> int:
        existing = self.session.scalar(
            select(SourceDocument.id).where(SourceDocument.sha256 == doc.sha256)
        )
        if existing is not None:
            return existing
        row = SourceDocument(
            sha256=doc.sha256,
            kind=doc.kind,
            schema_version=doc.content["schema_version"],
            file_name=doc.name,
            size_bytes=len(doc.raw),
            content=doc.content,
            first_batch_id=self._batch(),
        )
        self.session.add(row)
        self.session.flush()
        return row.id

    def _load_run_doc(self, doc: Document) -> None:
        try:
            with self._unit():
                run = self._get_run(doc.content["run_id"])
                doc_id = self._source_document(doc)
                if run.run_document_id != doc_id:
                    old = run.run_document_id
                    run.run_document_id = doc_id
                    self._audit(
                        "update",
                        "run",
                        run.run_code,
                        {"run_document": {"old": old, "new": doc.name}},
                    )
                    self.report.documents["run"]["loaded"] += 1
                else:
                    self.report.documents["run"]["identical"] += 1
        except SQLAlchemyError as exc:
            self._reject_doc(doc, f"database error: {exc.__class__.__name__}")

    def _link_sample(self, sample_run: SampleRun) -> None:
        """Q9: link to the biological sample with the same code; create it if there is none."""
        candidates = self.session.scalars(
            select(Sample).where(Sample.sample_code == sample_run.sample_code)
        ).all()
        if len(candidates) > 1:
            self.report.warnings.append(
                f"sample {sample_run.sample_code!r}: {len(candidates)} biological samples share "
                "this code; result not linked, link it in the web application"
            )
            return
        if candidates:
            sample = candidates[0]
        else:
            sample = Sample(sample_code=sample_run.sample_code, metadata_={})
            self.session.add(sample)
            self.session.flush()
            self._audit("create", "sample", sample.id, {"sample_code": sample.sample_code})
        sample_run.sample_id = sample.id

    def _load_key(
        self,
        run_code: str,
        sample_code: str,
        bundle: Bundle | None,
        sources: list[Membership],
        run_entry: dict[str, Any] | None,
    ) -> None:
        try:
            with self._unit():
                run = self._get_run(run_code)
                sample_run = self.session.scalar(
                    select(SampleRun).where(
                        SampleRun.run_id == run.id, SampleRun.sample_code == sample_code
                    )
                )
                if sample_run is None:
                    self._batch()
                    sample_run = SampleRun(run_id=run.id, sample_code=sample_code)
                    self.session.add(sample_run)
                    self.session.flush()
                    self._link_sample(sample_run)
                for m in sources:
                    self._membership(run.id, sample_code, m)
                if bundle is None:
                    if sample_run.current_version_id is None:
                        self.report.samples["no_results"] += 1
                    return
                self._version(sample_run, bundle, run_entry)
        except (LoadError, SQLAlchemyError) as exc:
            detail = str(exc) if isinstance(exc, LoadError) else f"database error: {exc}"
            if bundle is not None:
                self._reject_bundle(bundle, detail)
            else:
                self.report.rejected.append(f"sample {sample_code!r} in run {run_code!r}: {detail}")

    def _membership(self, run_id: int, sample_code: str, m: Membership) -> None:
        row = self.session.get(RunMembership, (run_id, sample_code, m.source))
        if row is None:
            self.session.add(
                RunMembership(
                    run_id=run_id,
                    sample_code=sample_code,
                    source=m.source,
                    source_sha256=m.sha256,
                    run_json_entry=m.entry,
                )
            )
        elif row.source_sha256 != m.sha256 or row.run_json_entry != m.entry:
            row.source_sha256, row.run_json_entry = m.sha256, m.entry
        self.session.flush()

    def _version(
        self, sample_run: SampleRun, bundle: Bundle, run_entry: dict[str, Any] | None
    ) -> None:
        fingerprint = bundle.fingerprint()
        same = self.session.scalar(
            select(ResultVersion.version_no).where(
                ResultVersion.sample_run_id == sample_run.id,
                ResultVersion.fingerprint == fingerprint,
            )
        )
        if same is not None:
            self.report.samples["unchanged"] += 1
            for doc in bundle.documents():
                self.report.documents[doc.kind]["identical"] += 1
            return
        warnings = list(bundle.warnings) + self._cross_check(bundle, run_entry)
        previous = (
            self.session.get(ResultVersion, sample_run.current_version_id)
            if sample_run.current_version_id is not None
            else None
        )
        if previous is not None:
            old_tools = set(
                self.session.scalars(
                    select(ToolResult.tool).where(ToolResult.version_id == previous.id)
                )
            )
            missing = sorted(old_tools - set(bundle.metrics))
            if missing:
                warnings.append(
                    f"sample {bundle.sample_id!r}: new version has no documents for "
                    f"{', '.join(missing)} (present in version {previous.version_no})"
                )
        max_no = self.session.scalar(
            select(func.max(ResultVersion.version_no)).where(
                ResultVersion.sample_run_id == sample_run.id
            )
        )
        version = ResultVersion(
            sample_run_id=sample_run.id,
            version_no=(max_no or 0) + 1,
            load_batch_id=self._batch(),
            fingerprint=fingerprint,
            has_qc=bundle.qc is not None,
            has_report=bundle.report is not None,
            load_warnings=warnings,
        )
        if bundle.qc is not None:
            self._apply_qc(version, bundle.qc)
        if bundle.report is not None:
            self._apply_report(version, bundle.report)
        for tool in sorted(bundle.metrics):
            version.tool_results.append(self._tool_result(bundle.metrics[tool]))
        self.session.add(version)
        self.session.flush()
        old_verdict = previous.verdict if previous is not None else None
        sample_run.current_version_id = version.id
        self.session.flush()
        self._audit(
            "load",
            "sample_run",
            sample_run.id,
            {
                "version": {
                    "old": previous.version_no if previous else None,
                    "new": version.version_no,
                },
                "verdict": {"old": old_verdict, "new": version.verdict},
            },
        )
        self.report.warnings += [w for w in warnings if w not in bundle.warnings]
        self.report.samples["new_version"] += 1
        if bundle.qc is None or bundle.report is None:
            self.report.samples["incomplete"] += 1
        for doc in bundle.documents():
            self.report.documents[doc.kind]["loaded"] += 1

    def _apply_qc(self, version: ResultVersion, doc: Document) -> None:
        qc = doc.content
        th, ctx = qc["thresholds"], qc["context"]
        version.qc_document_id = self._source_document(doc)
        version.verdict = qc["verdict"]
        version.evaluator_version = qc["evaluator"]["version"]
        version.thresholds_file = th["file"]
        version.thresholds_sha256 = th["sha256"]
        version.profile = th["profile"]
        version.read_length_profile = th["read_length_profile"]
        version.threshold_species = th["species"]
        version.threshold_chain = list(th["chain"])
        version.expected_taxid = ctx["expected_taxid"]
        version.context_read_length = ctx["read_length"]
        version.depth_basis = ctx["depth_basis"]
        version.reasons = list(qc["reasons"])
        version.advisory = list(qc["advisory"])
        version.notes = list(qc["notes"])
        version.unused_inputs = list(qc["unused_inputs"])
        version.qc_inputs = qc["inputs"]
        for ordinal, check in enumerate(qc["checks"]):
            value = check["value"]
            version.checks.append(
                QcCheck(
                    ordinal=ordinal,
                    metric=check["metric"],
                    value_num=value if _num(value) is not None else None,
                    value_text=value if isinstance(value, str) else None,
                    unit=check["unit"],
                    rule=check["rule"],
                    required=check["required"],
                    status=check["status"],
                    reason=check["reason"],
                )
            )

    def _apply_report(self, version: ResultVersion, doc: Document) -> None:
        rep = doc.content
        software = rep["software"]
        version.report_document_id = self._source_document(doc)
        version.report_run_id = rep["run_id"]
        version.meta = rep["meta"]
        version.report_generator_version = rep["generator"]["version"]
        version.pipeline = software["pipeline"]
        version.pipeline_version = software["pipeline_version"]
        version.nextflow_version = software["nextflow_version"]
        version.software = software
        version.typing_species = rep["typing"]["species"]

    def _tool_result(self, doc: Document) -> ToolResult:
        c = doc.content
        source, parser = c["source"], c["parser"]
        tool = source["tool"]
        result = ToolResult(
            document_id=self._source_document(doc),
            tool=tool,
            namespace=c["namespace"],
            status=c["status"],
            messages=c.get("messages"),
            tool_version=source["tool_version"],
            database_version=source.get("database_version"),
            parser_name=parser["name"],
            parser_version=parser["version"],
            schema_version=c["schema_version"],
            inputs=c.get("inputs"),
            data=c.get("data"),
        )
        for name, metric in c["metrics"].items():
            result.metrics.append(
                MetricValue(
                    metric_key=f"{tool}.{name}",
                    unit=metric["unit"],
                    **_split_value(metric["value"]),
                )
            )
        data = c.get("data") or {}
        if tool == "amrfinder" and isinstance(data.get("hits"), list):
            for i, hit in enumerate(h for h in data["hits"] if isinstance(h, dict)):
                result.amr_hits.append(
                    AmrHit(
                        ordinal=i,
                        symbol=_text(hit.get("symbol")),
                        name=_text(hit.get("name")),
                        type=_text(hit.get("type")),
                        subtype=_text(hit.get("subtype")),
                        class_=_text(hit.get("class")),
                        subclass=_text(hit.get("subclass")),
                        method=_text(hit.get("method")),
                        pct_identity=_num(hit.get("pct_identity")),
                        pct_coverage=_num(hit.get("pct_coverage")),
                        scope=_text(hit.get("scope")),
                        contig=_text(hit.get("contig")),
                        start_pos=_int(hit.get("start")),
                        stop_pos=_int(hit.get("stop")),
                        strand=_text(hit.get("strand")),
                        accession=_text(hit.get("accession")),
                    )
                )
        if tool == "bracken" and isinstance(data.get("abundances"), list):
            for i, item in enumerate(a for a in data["abundances"] if isinstance(a, dict)):
                result.abundances.append(
                    SpeciesAbundance(
                        ordinal=i,
                        name=_text(item.get("name")),
                        taxid=_int(item.get("taxid")),
                        reads=_int(item.get("reads")),
                        pct=_num(item.get("pct")),
                    )
                )
        return result

    def _cross_check(self, bundle: Bundle, entry: dict[str, Any] | None) -> list[str]:
        """Compare run.json with the documents; differences are warnings, never errors."""
        if entry is None:
            return []
        out: list[str] = []
        sid = bundle.sample_id
        verdict = bundle.qc.content["verdict"] if bundle.qc else None
        if entry["verdict"] != verdict:
            out.append(
                f"sample {sid!r}: run.json verdict {entry['verdict']} but qc.json verdict {verdict}"
            )
        if entry["report"] != (bundle.report is not None):
            out.append(
                f"sample {sid!r}: run.json report={entry['report']} but report.json "
                f"{'present' if bundle.report else 'absent'}"
            )
        metrics = {
            f"{d.content['source']['tool']}.{name}": m["value"]
            for d in bundle.metrics.values()
            for name, m in d.content["metrics"].items()
        }
        mine = summary_values(metrics, bundle.qc.content["checks"] if bundle.qc else [])
        for column, value in entry["values"].items():
            if column in mine and value is not None and mine[column] != value:
                out.append(
                    f"sample {sid!r}: run.json {column}={value} but documents give {mine[column]}"
                )
        return out

    def _load_order_doc(self, doc: Document) -> None:
        c = doc.content
        try:
            with self._unit():
                order = self.session.scalar(
                    select(SampleOrder).where(SampleOrder.order_code == c["order_id"])
                )
                changed = False
                if order is None:
                    order = SampleOrder(order_code=c["order_id"], meta=c["meta"])
                    self.session.add(order)
                    self.session.flush()
                    self._audit(
                        "create",
                        "sample_order",
                        order.id,
                        {"order_code": order.order_code, "source": doc.name},
                    )
                    changed = True
                elif order.meta is None and c["meta"]:
                    order.meta = c["meta"]
                    changed = True
                elif order.meta != c["meta"]:
                    self.report.warnings.append(
                        f"{doc.path}: meta differs from the stored order; stored value kept"
                    )
                for entry in c["samples"]:
                    changed |= self.link_order_sample(
                        order, entry["sample_id"], entry["run_id"], "order_json", str(doc.path)
                    )
                if changed:
                    self._source_document(doc)
                    self.report.documents["order"]["loaded"] += 1
                else:
                    self.report.documents["order"]["identical"] += 1
        except SQLAlchemyError as exc:
            self._reject_doc(doc, f"database error: {exc.__class__.__name__}")

    def link_order_sample(
        self, order: SampleOrder, sample_code: str, run_code: str | None, source: str, where: str
    ) -> bool:
        """Add an order -> sample link (D5: links are only ever added). Returns True if added."""
        query = select(SampleRun).where(SampleRun.sample_code == sample_code)
        if run_code is not None:
            query = query.join(Run, Run.id == SampleRun.run_id).where(Run.run_code == run_code)
        runs = self.session.scalars(query).all()
        sample_ids = {r.sample_id for r in runs if r.sample_id is not None}
        if not runs:
            self.report.warnings.append(
                f"{where}: sample {sample_code!r} (run {run_code or 'unknown'}) is not in the "
                "database; not linked to the order"
            )
            return False
        if len(sample_ids) != 1:
            self.report.warnings.append(
                f"{where}: sample {sample_code!r} (run {run_code or 'unknown'}) does not map to "
                "exactly one biological sample; link it in the web application"
            )
            return False
        sample_id = sample_ids.pop()
        if self.session.get(OrderSample, (order.id, sample_id)) is not None:
            return False
        self.session.add(OrderSample(order_id=order.id, sample_id=sample_id, source=source))
        self.session.flush()
        self._audit("link", "sample_order", order.id, {"sample_id": sample_id, "source": source})
        return True

    def _check_run_summaries(self, run_docs: list[Document]) -> None:
        for doc in run_docs:
            summary = doc.content["summary"]
            with self._read():
                rows = self.session.execute(
                    select(ResultVersion.verdict, func.count())
                    .select_from(SampleRun)
                    .join(Run, Run.id == SampleRun.run_id)
                    .outerjoin(ResultVersion, ResultVersion.id == SampleRun.current_version_id)
                    .where(Run.run_code == doc.content["run_id"])
                    .group_by(ResultVersion.verdict)
                ).all()
            counts: dict[str | None, int] = dict(rows)
            mine = {
                "n_samples": sum(counts.values()),
                "PASS": counts.get("PASS", 0),
                "WARN": counts.get("WARN", 0),
                "FAIL": counts.get("FAIL", 0),
                "missing": counts.get(None, 0),
            }
            diff = [f"{k} {summary[k]} vs {mine[k]}" for k in mine if summary[k] != mine[k]]
            if diff:
                self.report.warnings.append(
                    f"{doc.path}: summary differs from the database ({', '.join(diff)})"
                )

    def _finish(self) -> None:
        if self.opts.dry_run:
            return
        with self.session.begin():
            if self.batch_id is not None:
                batch = self.session.get(LoadBatch, self.batch_id)
                assert batch is not None
                batch.finished_at = dt.datetime.now(dt.timezone.utc)
                batch.counts = {
                    "documents": {k: dict(v) for k, v in self.report.documents.items()},
                    "samples": dict(self.report.samples),
                    "rejected": len(self.report.rejected),
                    "warnings": len(self.report.warnings),
                }
        refresh_summary(self.session)


def refresh_summary(session: Session) -> None:
    """Refresh the sample-table materialized view without blocking readers."""
    with session.begin():
        session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY sample_run_summary"))


def load_directory(session: Session, options: LoadOptions) -> LoadReport:
    return Loader(session, options).run()

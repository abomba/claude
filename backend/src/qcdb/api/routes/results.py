"""Sample table, sample detail, version history and CSV export."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from qcdb.api.common import (
    SUMMARY_LABELS,
    SUMMARY_VIEW,
    Page,
    PageParam,
    PageSizeParam,
    audit,
    csv_text,
    mask_paths,
    parse_sort,
    refresh_summary,
)
from qcdb.api.schemas import (
    AbundanceOut,
    AmrHitOut,
    CheckChange,
    CheckOut,
    Context,
    DocumentOut,
    MetricOut,
    OrderRef,
    OwnerRef,
    RelinkIn,
    ResultDetail,
    ResultItem,
    RunRef,
    SampleRef,
    SetCurrentIn,
    Software,
    Technical,
    Thresholds,
    ToolOut,
    ToolTechnical,
    Typing,
    VersionDetail,
    VersionDetailTech,
    VersionSummary,
)
from qcdb.api.security import DB, CurrentUser, Editor, Principal
from qcdb.db.models import (
    AmrHit,
    LoadBatch,
    MetricDefinition,
    MetricLabel,
    OrderSample,
    Owner,
    QcCheck,
    ResultVersion,
    Run,
    Sample,
    SampleOrder,
    SampleRun,
    SourceDocument,
    SpeciesAbundance,
    ToolResult,
)
from qcdb.summary_columns import SUMMARY_COLUMNS

router = APIRouter(prefix="/results", tags=["results"])
V = SUMMARY_VIEW.c
NAMESPACE_ORDER = [
    "input",
    "demux",
    "reads",
    "composition",
    "species",
    "assembly",
    "characterisation",
]
# Metric values that may contain server paths (trap 11): technical roles only.
TECHNICAL_METRICS = {"sylph.taxonomies_used"}
SORTABLE: dict[str, ColumnElement[Any]] = {
    c.name: c for c in SUMMARY_VIEW.c if c.name not in ("sample_id", "version_id", "run_id")
}


@dataclass
class ResultFilters:
    run: list[str] | None
    owner_id: int | None
    order_id: int | None
    species: list[str] | None
    verdict: list[str] | None
    profile: list[str] | None
    date_from: dt.date | None
    date_to: dt.date | None
    q: str | None
    amr_gene: str | None
    amr_class: str | None
    composition_species: str | None
    composition_min_pct: float


def result_filters(
    run: Annotated[list[str] | None, Query(description="run_id (repeatable)")] = None,
    owner_id: int | None = None,
    order_id: int | None = None,
    species: Annotated[list[str] | None, Query()] = None,
    verdict: Annotated[
        list[str] | None, Query(description="PASS, WARN, FAIL or none (no verdict)")
    ] = None,
    profile: Annotated[list[str] | None, Query()] = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    q: Annotated[str | None, Query(max_length=200, description="sample, run or order id")] = None,
    amr_gene: Annotated[str | None, Query(max_length=100)] = None,
    amr_class: Annotated[str | None, Query(max_length=100)] = None,
    composition_species: Annotated[str | None, Query(max_length=200)] = None,
    composition_min_pct: Annotated[float, Query(ge=0, le=100)] = 1.0,
) -> ResultFilters:
    for v in verdict or []:
        if v not in ("PASS", "WARN", "FAIL", "none"):
            raise HTTPException(422, f"invalid verdict {v!r}")
    return ResultFilters(
        run,
        owner_id,
        order_id,
        species,
        verdict,
        profile,
        date_from,
        date_to,
        q,
        amr_gene,
        amr_class,
        composition_species,
        composition_min_pct,
    )


Filters = Annotated[ResultFilters, Depends(result_filters)]


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def filtered(f: ResultFilters) -> Select[Any]:
    query = select(SUMMARY_VIEW)
    if f.run:
        query = query.where(V.run_code.in_(f.run))
    if f.verdict:
        values = [v for v in f.verdict if v != "none"]
        cond: ColumnElement[bool] = V.verdict.in_(values)
        if "none" in f.verdict:
            cond = or_(cond, V.verdict.is_(None))
        query = query.where(cond)
    if f.species:
        query = query.where(V.species.in_(f.species))
    if f.profile:
        query = query.where(V.profile.in_(f.profile))
    if f.date_from:
        query = query.where(V.run_date >= f.date_from)
    if f.date_to:
        query = query.where(V.run_date <= f.date_to)
    if f.owner_id is not None:
        query = query.where(
            exists(
                select(1)
                .select_from(OrderSample)
                .join(SampleOrder, SampleOrder.id == OrderSample.order_id)
                .where(OrderSample.sample_id == V.sample_id, SampleOrder.owner_id == f.owner_id)
            )
        )
    if f.order_id is not None:
        query = query.where(
            exists(
                select(1).where(
                    OrderSample.sample_id == V.sample_id, OrderSample.order_id == f.order_id
                )
            )
        )
    if f.q:
        like = _like(f.q)
        query = query.where(
            or_(
                V.sample_code.ilike(like, escape="\\"),
                V.run_code.ilike(like, escape="\\"),
                exists(
                    select(1)
                    .select_from(OrderSample)
                    .join(SampleOrder, SampleOrder.id == OrderSample.order_id)
                    .where(
                        OrderSample.sample_id == V.sample_id,
                        SampleOrder.order_code.ilike(like, escape="\\"),
                    )
                ),
            )
        )
    if f.amr_gene or f.amr_class:
        conds = [ToolResult.version_id == V.version_id]
        if f.amr_gene:
            conds.append(func.lower(AmrHit.symbol) == f.amr_gene.lower())
        if f.amr_class:
            conds.append(AmrHit.class_.ilike(_like(f.amr_class), escape="\\"))
        query = query.where(
            exists(
                select(1)
                .select_from(AmrHit)
                .join(ToolResult, ToolResult.id == AmrHit.tool_result_id)
                .where(*conds)
            )
        )
    if f.composition_species:
        query = query.where(
            exists(
                select(1)
                .select_from(SpeciesAbundance)
                .join(ToolResult, ToolResult.id == SpeciesAbundance.tool_result_id)
                .where(
                    ToolResult.version_id == V.version_id,
                    func.lower(SpeciesAbundance.name) == f.composition_species.lower(),
                    SpeciesAbundance.pct >= f.composition_min_pct,
                )
            )
        )
    return query


def orders_for(db: Session, sample_ids: set[int]) -> dict[int, list[OrderRef]]:
    if not sample_ids:
        return {}
    rows = db.execute(
        select(OrderSample.sample_id, SampleOrder, Owner)
        .join(SampleOrder, SampleOrder.id == OrderSample.order_id)
        .outerjoin(Owner, Owner.id == SampleOrder.owner_id)
        .where(OrderSample.sample_id.in_(sample_ids))
        .order_by(SampleOrder.order_code)
    ).all()
    result: dict[int, list[OrderRef]] = {}
    for sample_id, order, owner in rows:
        result.setdefault(sample_id, []).append(order_ref(order, owner))
    return result


def order_ref(order: SampleOrder, owner: Owner | None) -> OrderRef:
    return OrderRef(
        id=order.id,
        order_code=order.order_code,
        owner=OwnerRef(id=owner.id, full_name=owner.full_name, erased=owner.erased_at is not None)
        if owner
        else None,
    )


def _items(db: Session, rows: list[Any]) -> list[ResultItem]:
    orders = orders_for(db, {r.sample_id for r in rows if r.sample_id is not None})
    return [ResultItem(**dict(r._mapping), orders=orders.get(r.sample_id, [])) for r in rows]


@router.get("", response_model=Page[ResultItem], summary="Sample table (current results)")
def list_results(
    db: DB,
    user: CurrentUser,
    filters: Filters,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    sort: Annotated[str | None, Query(description="e.g. -run_date,sample_code")] = None,
) -> Page[ResultItem]:
    query = filtered(filters)
    order = parse_sort(sort, SORTABLE, ["-run_date", "run_code", "sample_code"])
    with db.begin():
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = db.execute(
            query.order_by(*order, V.sample_run_id).limit(page_size).offset((page - 1) * page_size)
        ).all()
        items = _items(db, list(rows))
    return Page[ResultItem](items=items, total=total, page=page, page_size=page_size)


CSV_KEYS = [
    "sample_code",
    "run_code",
    "run_date",
    "verdict",
    "profile",
    "species",
    "mlst_st",
    "serotype",
    "n_amr_genes",
    *[c.id for c in SUMMARY_COLUMNS],
    "orders",
    "owners",
    "has_qc",
    "has_report",
    "thresholds_sha256",
]
CSV_LABELS = {
    "sample_code": "Próbka",
    "run_code": "Przebieg",
    "run_date": "Data przebiegu",
    "verdict": "Werdykt",
    "profile": "Profil",
    "species": "Gatunek",
    "mlst_st": "MLST ST",
    "serotype": "Serotyp",
    "n_amr_genes": "Geny AMR [genes]",
    "orders": "Zlecenia",
    "owners": "Zleceniodawcy",
    "has_qc": "Ocena QC",
    "has_report": "Raport",
    "thresholds_sha256": "Progi (sha256)",
    **{k: f"{label} [{unit}]" if unit else label for k, (label, unit) in SUMMARY_LABELS.items()},
}


@router.get(
    "/export.csv",
    response_class=Response,
    summary="CSV export of the sample table",
    responses={200: {"content": {"text/csv": {}}}},
)
def export_results(
    db: DB,
    user: CurrentUser,
    filters: Filters,
    sort: Annotated[str | None, Query()] = None,
) -> Response:
    query = filtered(filters)
    order = parse_sort(sort, SORTABLE, ["-run_date", "run_code", "sample_code"])
    with db.begin():
        items = _items(
            db, list(db.execute(query.order_by(*order, V.sample_run_id).limit(100_000)).all())
        )
    rows = []
    for item in items:
        data = item.model_dump()
        data["orders"] = [o.order_code for o in item.orders]
        data["owners"] = sorted(
            {o.owner.full_name for o in item.orders if o.owner and o.owner.full_name}
        )
        rows.append([data[k] for k in CSV_KEYS])
    body = csv_text(CSV_KEYS, [CSV_LABELS[k] for k in CSV_KEYS], rows)
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="qcdb_wyniki.csv"'},
    )


# ---------------------------------------------------------------------- detail
def _labels(db: Session) -> tuple[dict[str, MetricDefinition], dict[str, str]]:
    defs = {d.key: d for d in db.scalars(select(MetricDefinition))}
    labels = {d.key: d.label for d in defs.values()}
    for row in db.scalars(select(MetricLabel).where(MetricLabel.lang == "pl")):
        labels[row.metric_key] = row.label
    return defs, labels


def _value(num: Any, text: Any, flag: Any) -> Any:
    for v in (num, text, flag):
        if v is not None:
            return v
    return None


def build_version(
    db: Session, sample_run: SampleRun, version: ResultVersion, principal: Principal
) -> VersionDetail:
    defs, labels = _labels(db)
    tools = sorted(
        db.scalars(select(ToolResult).where(ToolResult.version_id == version.id)).all(),
        key=lambda t: (
            NAMESPACE_ORDER.index(t.namespace) if t.namespace in NAMESPACE_ORDER else 99,
            t.tool,
        ),
    )
    values: dict[str, Any] = {}
    tool_out: list[ToolOut] = []
    amr: list[AmrHitOut] = []
    abundances: list[AbundanceOut] = []
    for tr in tools:
        metrics = []
        for mv in sorted(tr.metrics, key=lambda m: m.metric_key):
            value = _value(mv.value_num, mv.value_text, mv.value_bool)
            values[mv.metric_key] = value
            if mv.metric_key in TECHNICAL_METRICS and not principal.technical:
                continue
            d = defs.get(mv.metric_key)
            metrics.append(
                MetricOut(
                    key=mv.metric_key,
                    name=mv.metric_key.split(".", 1)[1],
                    label=labels.get(mv.metric_key, mv.metric_key),
                    unit=mv.unit,
                    value_type=d.value_type if d else "unknown",
                    value=value,
                    is_null=value is None,
                )
            )
        present = {m.metric_key for m in tr.metrics}
        absent = sorted(
            k
            for k, d in defs.items()
            if d.tool == tr.tool
            and k not in present
            and (principal.technical or k not in TECHNICAL_METRICS)
        )
        messages = tr.messages
        if messages is not None and not principal.technical:
            messages = [mask_paths(m) for m in messages]
        tool_out.append(
            ToolOut(
                tool=tr.tool,
                namespace=tr.namespace,
                status=tr.status,  # type: ignore[arg-type]
                messages=messages,
                tool_version=tr.tool_version,
                database_version=tr.database_version,
                parser_name=tr.parser_name,
                parser_version=tr.parser_version,
                schema_version=tr.schema_version,
                metrics=metrics,
                absent_metrics=absent,
            )
        )
        amr += [AmrHitOut.model_validate(h) for h in sorted(tr.amr_hits, key=lambda h: h.ordinal)]
        abundances += [
            AbundanceOut.model_validate(a) for a in sorted(tr.abundances, key=lambda a: a.ordinal)
        ]
    mlst = next((t for t in tools if t.tool == "mlst"), None)
    alleles = (mlst.data or {}).get("alleles") if mlst else None
    checks = [
        CheckOut(
            ordinal=c.ordinal,
            metric=c.metric,
            label=labels.get(c.metric),
            value=c.value_text if c.value_text is not None else c.value_num,
            unit=c.unit,
            rule=c.rule,
            required=c.required,
            status=c.status,  # type: ignore[arg-type]
            reason=c.reason,
        )
        for c in db.scalars(
            select(QcCheck).where(QcCheck.version_id == version.id).order_by(QcCheck.ordinal)
        )
    ]
    sw = version.software
    detail: dict[str, Any] = {
        "version_no": version.version_no,
        "created_at": version.created_at,
        "is_current": sample_run.current_version_id == version.id,
        "verdict": version.verdict,
        "has_qc": version.has_qc,
        "has_report": version.has_report,
        "evaluator_version": version.evaluator_version,
        "report_generator_version": version.report_generator_version,
        "thresholds": Thresholds(
            sha256=version.thresholds_sha256,
            profile=version.profile,
            read_length_profile=version.read_length_profile,
            species=version.threshold_species,
            chain=version.threshold_chain or [],
        )
        if version.has_qc and version.thresholds_sha256 and version.profile
        else None,
        "context": Context(
            expected_taxid=version.expected_taxid,
            read_length=version.context_read_length,
            depth_basis=version.depth_basis,
        )
        if version.has_qc
        else None,
        "checks": checks,
        "reasons": version.reasons or [],
        "advisory": version.advisory or [],
        "notes": version.notes or [],
        "unused_inputs": version.unused_inputs or [],
        "tools": tool_out,
        "typing": Typing(
            mlst_scheme=values.get("mlst.scheme"),
            mlst_sequence_type=values.get("mlst.sequence_type"),
            mlst_alleles=alleles if isinstance(alleles, dict) else None,
            seqsero2_serotype=values.get("seqsero2.serotype"),
            seqsero2_antigenic_profile=values.get("seqsero2.antigenic_profile"),
            ectyper_serotype=values.get("ectyper.serotype"),
            ectyper_qc_flag=values.get("ectyper.qc"),
            report_species=version.typing_species,
        ),
        "amr_hits": amr,
        "abundances": abundances,
        "software": Software(
            pipeline=sw.get("pipeline"),
            pipeline_version=sw.get("pipeline_version"),
            nextflow_version=sw.get("nextflow_version"),
            groups=sw.get("groups") or [],
            other=sw.get("other") or [],
        )
        if sw
        else None,
    }
    if not principal.technical:
        return VersionDetail(**detail)
    doc_ids = {t.document_id: t.tool for t in tools}
    for doc_id in (version.qc_document_id, version.report_document_id):
        if doc_id is not None:
            doc_ids.setdefault(doc_id, "")
    documents = [
        DocumentOut(kind=d.kind, tool=doc_ids[d.id] or None, file_name=d.file_name, sha256=d.sha256)
        for d in db.scalars(
            select(SourceDocument)
            .where(SourceDocument.id.in_(doc_ids))
            .order_by(SourceDocument.kind, SourceDocument.file_name)
        )
    ]
    batch = db.get(LoadBatch, version.load_batch_id)
    assert batch is not None
    tech = Technical(
        thresholds_file=version.thresholds_file,
        qc_inputs=version.qc_inputs,
        meta=version.meta,
        load_warnings=version.load_warnings,
        load_batch_id=batch.id,
        load_invoked_by=batch.invoked_by,
        load_source_dir=batch.source_dir,
        documents=documents,
        tools={t.tool: ToolTechnical(inputs=t.inputs, data=t.data) for t in tools},
    )
    return VersionDetailTech(**detail, technical=tech)


def _sample_run(db: Session, sample_run_id: int) -> SampleRun:
    sr = db.get(SampleRun, sample_run_id)
    if sr is None:
        raise HTTPException(404, "result not found")
    return sr


def _detail(
    db: Session, sr: SampleRun, version: ResultVersion | None, principal: Principal
) -> ResultDetail:
    run = db.get(Run, sr.run_id)
    assert run is not None
    sample = db.get(Sample, sr.sample_id) if sr.sample_id is not None else None
    n_versions = (
        db.scalar(
            select(func.count())
            .select_from(ResultVersion)
            .where(ResultVersion.sample_run_id == sr.id)
        )
        or 0
    )
    return ResultDetail(
        sample_run_id=sr.id,
        sample_code=sr.sample_code,
        run=RunRef(run_code=run.run_code, run_date=run.run_date),
        sample=SampleRef(id=sample.id, sample_code=sample.sample_code, metadata=sample.metadata_)
        if sample
        else None,
        orders=orders_for(db, {sample.id}).get(sample.id, []) if sample else [],
        n_versions=n_versions,
        version=build_version(db, sr, version, principal) if version else None,
    )


@router.get("/{sample_run_id}", response_model=ResultDetail, summary="Sample detail (current)")
def get_result(sample_run_id: int, db: DB, user: CurrentUser) -> ResultDetail:
    with db.begin():
        sr = _sample_run(db, sample_run_id)
        version = db.get(ResultVersion, sr.current_version_id) if sr.current_version_id else None
        return _detail(db, sr, version, user)


@router.get(
    "/{sample_run_id}/versions", response_model=list[VersionSummary], summary="Reprocessing history"
)
def list_versions(sample_run_id: int, db: DB, user: CurrentUser) -> list[VersionSummary]:
    with db.begin():
        sr = _sample_run(db, sample_run_id)
        versions = db.scalars(
            select(ResultVersion)
            .where(ResultVersion.sample_run_id == sr.id)
            .order_by(ResultVersion.version_no)
        ).all()
        checks: dict[int, dict[str, str]] = {}
        version_ids = [v.id for v in versions]
        for c in db.scalars(select(QcCheck).where(QcCheck.version_id.in_(version_ids))):
            checks.setdefault(c.version_id, {})[c.metric] = c.status
        out: list[VersionSummary] = []
        previous: dict[str, str] | None = None
        for v in versions:
            current = checks.get(v.id, {})
            changes = (
                []
                if previous is None
                else [
                    CheckChange(metric=m, old_status=previous.get(m), new_status=current.get(m))
                    for m in sorted(set(previous) | set(current))
                    if previous.get(m) != current.get(m)
                ]
            )
            out.append(
                VersionSummary(
                    version_no=v.version_no,
                    created_at=v.created_at,
                    is_current=v.id == sr.current_version_id,
                    verdict=v.verdict,  # type: ignore[arg-type]
                    has_qc=v.has_qc,
                    has_report=v.has_report,
                    thresholds_sha256=v.thresholds_sha256,
                    profile=v.profile,
                    check_changes=changes,
                )
            )
            previous = current
        return out


def _version_by_no(db: Session, sr: SampleRun, version_no: int) -> ResultVersion:
    version = db.scalar(
        select(ResultVersion).where(
            ResultVersion.sample_run_id == sr.id, ResultVersion.version_no == version_no
        )
    )
    if version is None:
        raise HTTPException(404, "version not found")
    return version


@router.get(
    "/{sample_run_id}/versions/{version_no}",
    response_model=ResultDetail,
    summary="Sample detail of one version",
)
def get_version(sample_run_id: int, version_no: int, db: DB, user: CurrentUser) -> ResultDetail:
    with db.begin():
        sr = _sample_run(db, sample_run_id)
        return _detail(db, sr, _version_by_no(db, sr, version_no), user)


@router.post(
    "/{sample_run_id}/current",
    response_model=ResultDetail,
    summary="Choose the current version (Q5)",
)
def set_current(sample_run_id: int, body: SetCurrentIn, db: DB, user: Editor) -> ResultDetail:
    with db.begin():
        sr = _sample_run(db, sample_run_id)
        version = _version_by_no(db, sr, body.version_no)
        old = db.get(ResultVersion, sr.current_version_id) if sr.current_version_id else None
        if old is None or old.id != version.id:
            sr.current_version_id = version.id
            audit(
                db,
                user,
                "set_current",
                "sample_run",
                sr.id,
                {
                    "version": {"old": old.version_no if old else None, "new": version.version_no},
                    "verdict": {"old": old.verdict if old else None, "new": version.verdict},
                },
            )
    refresh_summary(db)
    return get_result(sample_run_id, db, user)


@router.put(
    "/{sample_run_id}/sample",
    response_model=ResultDetail,
    summary="Link the result to another biological sample (Q9)",
)
def relink(sample_run_id: int, body: RelinkIn, db: DB, user: Editor) -> ResultDetail:
    with db.begin():
        sr = _sample_run(db, sample_run_id)
        if body.sample_id is not None and db.get(Sample, body.sample_id) is None:
            raise HTTPException(404, "sample not found")
        if sr.sample_id != body.sample_id:
            audit(
                db,
                user,
                "relink",
                "sample_run",
                sr.id,
                {"sample_id": {"old": sr.sample_id, "new": body.sample_id}},
            )
            sr.sample_id = body.sample_id
    refresh_summary(db)
    return get_result(sample_run_id, db, user)

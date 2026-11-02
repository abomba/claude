"""Runs: summary counts, run date, outliers; metric definitions and trends."""

from __future__ import annotations

import datetime as dt
import statistics
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from qcdb.api.common import (
    SUMMARY_LABELS,
    SUMMARY_VIEW,
    Page,
    PageParam,
    PageSizeParam,
    audit,
    parse_sort,
    refresh_summary,
)
from qcdb.api.schemas import (
    MetricDefinitionOut,
    OutlierOut,
    RunDetail,
    RunOut,
    RunPatch,
    ThresholdChange,
    TrendGroup,
    TrendOut,
    TrendPoint,
)
from qcdb.api.security import DB, CurrentUser, Editor
from qcdb.db.models import (
    MetricDefinition,
    MetricLabel,
    MetricValue,
    QcCheck,
    Run,
    SourceDocument,
    ToolResult,
)
from qcdb.loader.validate import TOOL_NAMESPACES
from qcdb.summary_columns import SUMMARY_COLUMNS

router = APIRouter(tags=["runs and trends"])
V = SUMMARY_VIEW.c

_counts = (
    func.count(V.sample_run_id).label("n_samples"),
    func.count().filter(V.verdict == "PASS").label("n_pass"),
    func.count().filter(V.verdict == "WARN").label("n_warn"),
    func.count().filter(V.verdict == "FAIL").label("n_fail"),
    func.count(V.sample_run_id).filter(V.verdict.is_(None)).label("n_missing"),
)


def _run_query() -> Any:
    return (
        select(Run.run_code, Run.run_date, Run.run_date_source, Run.run_document_id, *_counts)
        .select_from(Run)
        .outerjoin(SUMMARY_VIEW, V.run_id == Run.id)
        .group_by(Run.id)
    )


@router.get("/runs", response_model=Page[RunOut], summary="Runs with verdict counts")
def list_runs(
    db: DB,
    user: CurrentUser,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    sort: Annotated[str | None, Query()] = None,
) -> Page[RunOut]:
    allowed: dict[str, Any] = {"run_code": Run.run_code, "run_date": Run.run_date}
    order = parse_sort(sort, allowed, ["-run_date", "-run_code"])
    with db.begin():
        total = db.scalar(select(func.count()).select_from(Run)) or 0
        rows = db.execute(
            _run_query().order_by(*order).limit(page_size).offset((page - 1) * page_size)
        ).all()
    items = [
        RunOut(**{k: v for k, v in r._mapping.items() if k != "run_document_id"}) for r in rows
    ]
    return Page[RunOut](items=items, total=total, page=page, page_size=page_size)


def _get_run(db: Session, run_code: str) -> Run:
    run = db.scalar(select(Run).where(Run.run_code == run_code))
    if run is None:
        raise HTTPException(404, "run not found")
    return run


@router.get("/runs/{run_code}", response_model=RunDetail, summary="Run summary")
def get_run(run_code: str, db: DB, user: CurrentUser) -> RunDetail:
    with db.begin():
        _get_run(db, run_code)
        row = db.execute(_run_query().where(Run.run_code == run_code)).one()
        data = dict(row._mapping)
        summary = None
        if data["run_document_id"] is not None:
            doc = db.get(SourceDocument, data["run_document_id"])
            summary = dict(doc.content["summary"]) if doc else None
    data.pop("run_document_id")
    matches = None
    if summary is not None:
        matches = (
            summary.get("n_samples"),
            summary.get("PASS"),
            summary.get("WARN"),
            summary.get("FAIL"),
            summary.get("missing"),
        ) == (data["n_samples"], data["n_pass"], data["n_warn"], data["n_fail"], data["n_missing"])
    return RunDetail(**data, run_document_summary=summary, summary_matches_run_document=matches)


@router.patch("/runs/{run_code}", response_model=RunDetail, summary="Set or change the run date")
def patch_run(run_code: str, body: RunPatch, db: DB, user: Editor) -> RunDetail:
    with db.begin():
        run = _get_run(db, run_code)
        if run.run_date != body.run_date:
            audit(
                db,
                user,
                "update",
                "run",
                run.run_code,
                {
                    "run_date": {
                        "old": run.run_date.isoformat() if run.run_date else None,
                        "new": body.run_date.isoformat() if body.run_date else None,
                    }
                },
            )
            run.run_date = body.run_date
            run.run_date_source = "ui" if body.run_date else None
    refresh_summary(db)
    return get_run(run_code, db, user)


@router.get(
    "/runs/{run_code}/outliers",
    response_model=list[OutlierOut],
    summary="Statistical outliers within the run (Tukey fences, n >= 5; not a verdict)",
)
def run_outliers(run_code: str, db: DB, user: CurrentUser) -> list[OutlierOut]:
    with db.begin():
        run = _get_run(db, run_code)
        rows = db.execute(select(SUMMARY_VIEW).where(V.run_id == run.id)).all()
    out: list[OutlierOut] = []
    for col in SUMMARY_COLUMNS:
        values = [
            (r.sample_run_id, r.sample_code, r._mapping[col.id])
            for r in rows
            if r._mapping[col.id] is not None
        ]
        if len(values) < 5:
            continue
        q1, _, q3 = statistics.quantiles([float(v) for _, _, v in values], n=4, method="inclusive")
        iqr = q3 - q1
        low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        label, unit = SUMMARY_LABELS[col.id]
        for sr_id, code, value in values:
            if float(value) < low or float(value) > high:
                out.append(
                    OutlierOut(
                        column=col.id,
                        label=label,
                        unit=unit,
                        sample_run_id=sr_id,
                        sample_code=code,
                        value=value,
                        low_fence=round(low, 4),
                        high_fence=round(high, 4),
                        direction="low" if float(value) < low else "high",
                    )
                )
    return out


# ---------------------------------------------------------------------- metrics and trends
def _definitions(db: Session) -> list[MetricDefinitionOut]:
    labels = {
        r.metric_key: r for r in db.scalars(select(MetricLabel).where(MetricLabel.lang == "pl"))
    }
    out = []
    for d in db.scalars(select(MetricDefinition).order_by(MetricDefinition.key)):
        pl = labels.get(d.key)
        out.append(
            MetricDefinitionOut(
                key=d.key,
                source="dictionary",
                tool=d.tool,
                namespace=TOOL_NAMESPACES.get(d.tool),
                unit=d.unit,
                value_type=d.value_type,
                numeric=d.value_type in ("int", "float"),
                range_min=d.range_min,
                range_max=d.range_max,
                label=pl.label if pl else d.label,
                label_en=d.label,
                description=(pl.description if pl and pl.description else d.description),
            )
        )
    known = {d.key for d in out}
    for metric, unit in db.execute(
        select(QcCheck.metric, func.min(QcCheck.unit))
        .where(QcCheck.value_num.is_not(None))
        .group_by(QcCheck.metric)
        .order_by(QcCheck.metric)
    ):
        if metric not in known:
            out.append(
                MetricDefinitionOut(
                    key=metric,
                    source="check",
                    tool=None,
                    namespace=None,
                    unit=unit,
                    value_type="float",
                    numeric=True,
                    range_min=None,
                    range_max=None,
                    label=metric,
                    label_en=None,
                    description="value computed by qceval (QC check)",
                )
            )
    return out


@router.get(
    "/metrics",
    response_model=list[MetricDefinitionOut],
    summary="Metric definitions with Polish labels, plus numeric QC-check metrics",
)
def list_metrics(db: DB, user: CurrentUser) -> list[MetricDefinitionOut]:
    with db.begin():
        return _definitions(db)


def _stats(key: str | None, values: list[Decimal]) -> TrendGroup:
    data = sorted(float(v) for v in values)
    if len(data) >= 2:
        q1, median, q3 = statistics.quantiles(data, n=4, method="inclusive")
    else:
        q1 = median = q3 = data[0]
    return TrendGroup(
        key=key,
        n=len(data),
        min=data[0],
        q1=round(q1, 4),
        median=round(median, 4),
        q3=round(q3, 4),
        max=data[-1],
    )


@router.get("/trends", response_model=TrendOut, summary="One metric over time and by group")
def trends(
    db: DB,
    user: CurrentUser,
    metric: Annotated[str, Query(description="metric key, e.g. fastp.pct_q30_after_filter")],
    group_by: Literal["species", "run", "profile"] = "species",
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    species: Annotated[list[str] | None, Query()] = None,
    profile: Annotated[list[str] | None, Query()] = None,
    run: Annotated[list[str] | None, Query()] = None,
) -> TrendOut:
    with db.begin():
        definitions = {d.key: d for d in _definitions(db)}
        d = definitions.get(metric)
        if d is None or not d.numeric:
            raise HTTPException(404, f"unknown or non-numeric metric {metric!r}")
        if d.source == "dictionary":
            value_col: Any = MetricValue.value_num
            query = (
                select(SUMMARY_VIEW, value_col.label("value"))
                .select_from(MetricValue)
                .join(ToolResult, ToolResult.id == MetricValue.tool_result_id)
                .join(SUMMARY_VIEW, V.version_id == ToolResult.version_id)
                .where(MetricValue.metric_key == metric, value_col.is_not(None))
            )
        else:
            query = (
                select(SUMMARY_VIEW, QcCheck.value_num.label("value"))
                .select_from(QcCheck)
                .join(SUMMARY_VIEW, V.version_id == QcCheck.version_id)
                .where(QcCheck.metric == metric, QcCheck.value_num.is_not(None))
            )
        if date_from:
            query = query.where(V.run_date >= date_from)
        if date_to:
            query = query.where(V.run_date <= date_to)
        if species:
            query = query.where(V.species.in_(species))
        if profile:
            query = query.where(V.profile.in_(profile))
        if run:
            query = query.where(V.run_code.in_(run))
        rows = db.execute(
            query.order_by(V.run_date.asc().nulls_last(), V.run_code, V.sample_code)
        ).all()
    points = []
    excluded = 0
    for r in rows:
        m = r._mapping
        if m["run_date"] is None:
            excluded += 1
            continue
        points.append(
            TrendPoint(
                sample_run_id=m["sample_run_id"],
                sample_code=m["sample_code"],
                run_code=m["run_code"],
                run_date=m["run_date"],
                value=m["value"],
                verdict=m["verdict"],
                species=m["species"],
                profile=m["profile"],
                thresholds_sha256=m["thresholds_sha256"],
            )
        )
    changes: list[ThresholdChange] = []
    previous: str | None = None
    for p in points:
        if p.thresholds_sha256 is None:
            continue
        if previous is not None and p.thresholds_sha256 != previous:
            changes.append(
                ThresholdChange(
                    run_date=p.run_date,
                    run_code=p.run_code,
                    previous_sha256=previous,
                    sha256=p.thresholds_sha256,
                )
            )
        previous = p.thresholds_sha256
    grouped: dict[str | None, list[Decimal]] = {}
    for p in points:
        key = {"species": p.species, "run": p.run_code, "profile": p.profile}[group_by]
        grouped.setdefault(key, []).append(Decimal(str(p.value)))
    groups = [_stats(k, v) for k, v in sorted(grouped.items(), key=lambda kv: str(kv[0]))]
    return TrendOut(
        metric=metric,
        label=d.label,
        unit=d.unit,
        points=points,
        groups=groups,
        group_by=group_by,
        threshold_changes=changes,
        excluded_without_date=excluded,
    )

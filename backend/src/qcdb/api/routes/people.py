"""Owners, orders, biological samples and configurable sample fields (CRUD)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from qcdb.api.common import Page, PageParam, PageSizeParam, audit, parse_sort
from qcdb.api.routes.results import _like, order_ref, orders_for
from qcdb.api.schemas import (
    AssignIn,
    OrderDetail,
    OrderIn,
    OrderOut,
    OrderPatch,
    OrderTechDetail,
    OrderTechOut,
    OwnerContactOut,
    OwnerIn,
    OwnerOut,
    OwnerPatch,
    OwnerRef,
    ResultRef,
    SampleBrief,
    SampleFieldIn,
    SampleFieldOut,
    SampleFieldPatch,
    SampleIn,
    SampleOut,
    SamplePatch,
)
from qcdb.api.security import DB, Admin, CurrentUser, Editor, Principal
from qcdb.db.models import (
    OrderSample,
    Owner,
    ResultVersion,
    Run,
    Sample,
    SampleFieldDefinition,
    SampleOrder,
    SampleRun,
)

router = APIRouter(tags=["owners, orders and samples"])
PERSONAL_FIELDS = ("full_name", "email")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------------- owners
def _owner_out(db: Session, owner: Owner, principal: Principal) -> OwnerOut:
    n_orders = (
        db.scalar(
            select(func.count()).select_from(SampleOrder).where(SampleOrder.owner_id == owner.id)
        )
        or 0
    )
    data: dict[str, Any] = {
        "id": owner.id,
        "full_name": owner.full_name,
        "erased": owner.erased_at is not None,
        "erased_at": owner.erased_at,
        "created_at": owner.created_at,
        "updated_at": owner.updated_at,
        "n_orders": n_orders,
    }
    if principal.technical:
        return OwnerContactOut(**data, email=owner.email)
    return OwnerOut(**data)


def _owner(db: Session, owner_id: int) -> Owner:
    owner = db.get(Owner, owner_id)
    if owner is None:
        raise HTTPException(404, "owner not found")
    return owner


@router.get(
    "/owners",
    response_model=Page[OwnerContactOut | OwnerOut],
    summary="Owners (e-mail only for bioinformatician/admin)",
)
def list_owners(
    db: DB,
    user: CurrentUser,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: Annotated[str | None, Query()] = None,
) -> Page[OwnerContactOut | OwnerOut]:
    query = select(Owner)
    if q:
        query = query.where(Owner.full_name.ilike(_like(q), escape="\\"))
    order = parse_sort(
        sort, {"full_name": Owner.full_name, "created_at": Owner.created_at}, ["full_name"]
    )
    with db.begin():
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        owners = db.scalars(
            query.order_by(*order, Owner.id).limit(page_size).offset((page - 1) * page_size)
        ).all()
        items = [_owner_out(db, o, user) for o in owners]
    return Page[OwnerContactOut | OwnerOut](
        items=items, total=total, page=page, page_size=page_size
    )


@router.post("/owners", response_model=OwnerContactOut, status_code=201)
def create_owner(body: OwnerIn, db: DB, user: Editor) -> OwnerOut:
    with db.begin():
        owner = Owner(full_name=body.full_name, email=body.email)
        db.add(owner)
        db.flush()
        audit(
            db,
            user,
            "create",
            "owner",
            owner.id,
            {f: "set" for f in PERSONAL_FIELDS if getattr(body, f)},
        )
        return _owner_out(db, owner, user)


@router.get("/owners/{owner_id}", response_model=OwnerContactOut | OwnerOut)
def get_owner(owner_id: int, db: DB, user: CurrentUser) -> OwnerOut:
    with db.begin():
        return _owner_out(db, _owner(db, owner_id), user)


@router.patch("/owners/{owner_id}", response_model=OwnerContactOut)
def patch_owner(owner_id: int, body: OwnerPatch, db: DB, user: Editor) -> OwnerOut:
    with db.begin():
        owner = _owner(db, owner_id)
        if owner.erased_at is not None:
            raise HTTPException(409, "owner data was erased")
        changes: dict[str, Any] = {}
        for field in body.model_fields_set:
            value = getattr(body, field)
            if field == "full_name" and value is None:
                raise HTTPException(422, "full_name is required")
            if getattr(owner, field) != value:
                setattr(owner, field, value)
                changes[field] = "changed"  # personal data: values are not audited
        if changes:
            owner.updated_at = _now()
            audit(db, user, "update", "owner", owner.id, changes)
        return _owner_out(db, owner, user)


@router.delete("/owners/{owner_id}", status_code=204, response_class=Response)
def delete_owner(owner_id: int, db: DB, user: Editor) -> Response:
    with db.begin():
        owner = _owner(db, owner_id)
        if db.scalar(
            select(func.count()).select_from(SampleOrder).where(SampleOrder.owner_id == owner.id)
        ):
            raise HTTPException(409, "owner has orders; erase personal data instead")
        db.delete(owner)
        audit(db, user, "delete", "owner", owner_id, {})
    return Response(status_code=204)


@router.post(
    "/owners/{owner_id}/erase",
    response_model=OwnerContactOut,
    summary="Erase personal data (pseudonymise; orders and results stay)",
)
def erase_owner(owner_id: int, db: DB, user: Admin) -> OwnerOut:
    with db.begin():
        owner = _owner(db, owner_id)
        if owner.erased_at is not None:
            raise HTTPException(409, "already erased")
        owner.full_name = None
        owner.email = None
        owner.erased_at = owner.updated_at = _now()
        audit(db, user, "erase", "owner", owner.id, dict.fromkeys(PERSONAL_FIELDS, "erased"))
        return _owner_out(db, owner, user)


# ---------------------------------------------------------------------- orders
def _order(db: Session, order_id: int) -> SampleOrder:
    order = db.get(SampleOrder, order_id)
    if order is None:
        raise HTTPException(404, "order not found")
    return order


def _order_out(
    db: Session, order: SampleOrder, principal: Principal, detail: bool = False
) -> OrderOut:
    owner = db.get(Owner, order.owner_id) if order.owner_id else None
    samples = db.scalars(
        select(Sample)
        .join(OrderSample, OrderSample.sample_id == Sample.id)
        .where(OrderSample.order_id == order.id)
        .order_by(Sample.sample_code)
    ).all()
    data: dict[str, Any] = {
        "id": order.id,
        "order_code": order.order_code,
        "owner": OwnerRef(
            id=owner.id, full_name=owner.full_name, erased=owner.erased_at is not None
        )
        if owner
        else None,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "n_samples": len(samples),
    }
    if detail:
        data["samples"] = [SampleBrief(id=s.id, sample_code=s.sample_code) for s in samples]
        return (
            OrderTechDetail(**data, meta=order.meta) if principal.technical else OrderDetail(**data)
        )
    return OrderTechOut(**data, meta=order.meta) if principal.technical else OrderOut(**data)


def _check_owner(db: Session, owner_id: int | None) -> None:
    if owner_id is None:
        return
    owner = db.get(Owner, owner_id)
    if owner is None:
        raise HTTPException(422, "owner does not exist")
    if owner.erased_at is not None:
        raise HTTPException(409, "owner data was erased")


@router.get("/orders", response_model=Page[OrderTechOut | OrderOut])
def list_orders(
    db: DB,
    user: CurrentUser,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    owner_id: int | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    sort: Annotated[str | None, Query()] = None,
) -> Page[OrderTechOut | OrderOut]:
    query = select(SampleOrder)
    if owner_id is not None:
        query = query.where(SampleOrder.owner_id == owner_id)
    if q:
        query = query.where(SampleOrder.order_code.ilike(_like(q), escape="\\"))
    order = parse_sort(
        sort,
        {"order_code": SampleOrder.order_code, "created_at": SampleOrder.created_at},
        ["order_code"],
    )
    with db.begin():
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = db.scalars(
            query.order_by(*order, SampleOrder.id).limit(page_size).offset((page - 1) * page_size)
        ).all()
        items = [_order_out(db, o, user) for o in rows]
    return Page[OrderTechOut | OrderOut](items=items, total=total, page=page, page_size=page_size)


@router.post("/orders", response_model=OrderTechDetail, status_code=201)
def create_order(body: OrderIn, db: DB, user: Editor) -> OrderOut:
    try:
        with db.begin():
            _check_owner(db, body.owner_id)
            order = SampleOrder(order_code=body.order_code, owner_id=body.owner_id)
            db.add(order)
            db.flush()
            audit(
                db,
                user,
                "create",
                "sample_order",
                order.id,
                {"order_code": body.order_code, "owner_id": body.owner_id},
            )
            return _order_out(db, order, user, detail=True)
    except IntegrityError:
        raise HTTPException(409, "order_code already exists") from None


@router.get("/orders/{order_id}", response_model=OrderTechDetail | OrderDetail)
def get_order(order_id: int, db: DB, user: CurrentUser) -> OrderOut:
    with db.begin():
        return _order_out(db, _order(db, order_id), user, detail=True)


@router.patch(
    "/orders/{order_id}",
    response_model=OrderTechDetail,
    summary="Rename an order or assign its owner",
)
def patch_order(order_id: int, body: OrderPatch, db: DB, user: Editor) -> OrderOut:
    try:
        with db.begin():
            order = _order(db, order_id)
            changes: dict[str, Any] = {}
            for field in body.model_fields_set:
                value = getattr(body, field)
                if field == "order_code" and value is None:
                    raise HTTPException(422, "order_code is required")
                if field == "owner_id":
                    _check_owner(db, value)
                if getattr(order, field) != value:
                    changes[field] = {"old": getattr(order, field), "new": value}
                    setattr(order, field, value)
            if changes:
                order.updated_at = _now()
                audit(db, user, "update", "sample_order", order.id, changes)
            db.flush()
            return _order_out(db, order, user, detail=True)
    except IntegrityError:
        raise HTTPException(409, "order_code already exists") from None


@router.delete("/orders/{order_id}", status_code=204, response_class=Response)
def delete_order(order_id: int, db: DB, user: Editor) -> Response:
    with db.begin():
        order = _order(db, order_id)
        if db.scalar(
            select(func.count()).select_from(OrderSample).where(OrderSample.order_id == order.id)
        ):
            raise HTTPException(409, "order has samples; unassign them first")
        db.delete(order)
        audit(db, user, "delete", "sample_order", order_id, {"order_code": order.order_code})
    return Response(status_code=204)


@router.post(
    "/orders/{order_id}/samples",
    response_model=OrderTechDetail,
    summary="Assign samples to an order",
)
def assign_samples(order_id: int, body: AssignIn, db: DB, user: Editor) -> OrderOut:
    with db.begin():
        order = _order(db, order_id)
        found = set(db.scalars(select(Sample.id).where(Sample.id.in_(body.sample_ids))))
        missing = sorted(set(body.sample_ids) - found)
        if missing:
            raise HTTPException(422, f"samples not found: {missing}")
        for sample_id in sorted(found):
            if db.get(OrderSample, (order.id, sample_id)) is None:
                db.add(OrderSample(order_id=order.id, sample_id=sample_id, source="ui"))
                audit(
                    db,
                    user,
                    "link",
                    "sample_order",
                    order.id,
                    {"sample_id": sample_id, "source": "ui"},
                )
        db.flush()
        return _order_out(db, order, user, detail=True)


@router.delete("/orders/{order_id}/samples/{sample_id}", status_code=204, response_class=Response)
def unassign_sample(order_id: int, sample_id: int, db: DB, user: Editor) -> Response:
    with db.begin():
        link = db.get(OrderSample, (order_id, sample_id))
        if link is None:
            raise HTTPException(404, "sample is not in this order")
        db.delete(link)
        audit(db, user, "unlink", "sample_order", order_id, {"sample_id": sample_id})
    return Response(status_code=204)


# ---------------------------------------------------------------------- sample fields
def _fields(db: Session) -> dict[str, SampleFieldDefinition]:
    return {f.key: f for f in db.scalars(select(SampleFieldDefinition))}


@router.get(
    "/sample-fields",
    response_model=list[SampleFieldOut],
    summary="Configurable sample metadata fields",
)
def list_fields(db: DB, user: CurrentUser) -> list[SampleFieldOut]:
    with db.begin():
        rows = db.scalars(
            select(SampleFieldDefinition).order_by(
                SampleFieldDefinition.ordinal, SampleFieldDefinition.key
            )
        )
        return [SampleFieldOut.model_validate(f) for f in rows]


def _check_choices(data_type: str, choices: list[str] | None) -> None:
    if data_type == "choice" and not choices:
        raise HTTPException(422, "a choice field needs at least one choice")
    if data_type != "choice" and choices:
        raise HTTPException(422, "choices are only allowed for choice fields")


@router.post("/sample-fields", response_model=SampleFieldOut, status_code=201)
def create_field(body: SampleFieldIn, db: DB, user: Admin) -> SampleFieldOut:
    _check_choices(body.data_type, body.choices)
    try:
        with db.begin():
            field = SampleFieldDefinition(**body.model_dump())
            db.add(field)
            db.flush()
            audit(db, user, "create", "sample_field_definition", field.key, body.model_dump())
            return SampleFieldOut.model_validate(field)
    except IntegrityError:
        raise HTTPException(409, "field key already exists") from None


@router.patch(
    "/sample-fields/{key}",
    response_model=SampleFieldOut,
    summary="Change a field (key and type are immutable; deactivate instead of delete)",
)
def patch_field(key: str, body: SampleFieldPatch, db: DB, user: Admin) -> SampleFieldOut:
    with db.begin():
        field = db.scalar(select(SampleFieldDefinition).where(SampleFieldDefinition.key == key))
        if field is None:
            raise HTTPException(404, "field not found")
        changes: dict[str, Any] = {}
        for name in body.model_fields_set:
            value = getattr(body, name)
            if value is None and name != "choices":
                raise HTTPException(422, f"{name} cannot be null")
            if getattr(field, name) != value:
                changes[name] = {"old": getattr(field, name), "new": value}
                setattr(field, name, value)
        _check_choices(field.data_type, field.choices)
        if changes:
            audit(db, user, "update", "sample_field_definition", field.key, changes)
        db.flush()
        return SampleFieldOut.model_validate(field)


# ---------------------------------------------------------------------- samples
def validate_metadata(fields: dict[str, SampleFieldDefinition], key: str, value: Any) -> Any:
    field = fields.get(key)
    if field is None or not field.is_active:
        raise HTTPException(422, f"unknown or inactive metadata field {key!r}")
    kind = field.data_type
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise HTTPException(422, f"{key}: expected a number")
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            raise HTTPException(422, f"{key}: expected a number") from None
        if not number.is_finite():
            raise HTTPException(422, f"{key}: expected a number")
        return number
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(422, f"{key}: expected a non-empty string")
    if kind == "date":
        try:
            return dt.date.fromisoformat(value).isoformat()
        except ValueError:
            raise HTTPException(422, f"{key}: expected YYYY-MM-DD") from None
    if kind == "choice" and value not in (field.choices or []):
        raise HTTPException(422, f"{key}: must be one of {field.choices}")
    return value


def _missing_required(
    fields: dict[str, SampleFieldDefinition], metadata: dict[str, Any]
) -> list[str]:
    return sorted(k for k, f in fields.items() if f.is_active and f.required and k not in metadata)


def _sample(db: Session, sample_id: int) -> Sample:
    sample = db.get(Sample, sample_id)
    if sample is None:
        raise HTTPException(404, "sample not found")
    return sample


def _sample_out(db: Session, sample: Sample) -> SampleOut:
    results = db.execute(
        select(
            SampleRun.id,
            Run.run_code,
            Run.run_date,
            ResultVersion.verdict,
            SampleRun.current_version_id,
        )
        .join(Run, Run.id == SampleRun.run_id)
        .outerjoin(ResultVersion, ResultVersion.id == SampleRun.current_version_id)
        .where(SampleRun.sample_id == sample.id)
        .order_by(Run.run_date, Run.run_code)
    ).all()
    return SampleOut(
        id=sample.id,
        sample_code=sample.sample_code,
        metadata=sample.metadata_,
        missing_required=_missing_required(_fields(db), sample.metadata_),
        orders=orders_for(db, {sample.id}).get(sample.id, []),
        results=[
            ResultRef(
                sample_run_id=r[0],
                run_code=r[1],
                run_date=r[2],
                verdict=r[3],  # type: ignore[arg-type]
                has_results=r[4] is not None,
            )
            for r in results
        ],
        created_at=sample.created_at,
        updated_at=sample.updated_at,
    )


@router.get("/samples", response_model=Page[SampleOut], summary="Biological samples")
def list_samples(
    db: DB,
    user: CurrentUser,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    q: Annotated[str | None, Query(max_length=200)] = None,
    order_id: int | None = None,
    sort: Annotated[str | None, Query()] = None,
) -> Page[SampleOut]:
    query = select(Sample)
    if q:
        query = query.where(Sample.sample_code.ilike(_like(q), escape="\\"))
    if order_id is not None:
        query = query.join(OrderSample, OrderSample.sample_id == Sample.id).where(
            OrderSample.order_id == order_id
        )
    order = parse_sort(
        sort, {"sample_code": Sample.sample_code, "created_at": Sample.created_at}, ["sample_code"]
    )
    with db.begin():
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = db.scalars(
            query.order_by(*order, Sample.id).limit(page_size).offset((page - 1) * page_size)
        ).all()
        items = [_sample_out(db, s) for s in rows]
    return Page[SampleOut](items=items, total=total, page=page, page_size=page_size)


@router.post("/samples", response_model=SampleOut, status_code=201)
def create_sample(body: SampleIn, db: DB, user: Editor) -> SampleOut:
    with db.begin():
        fields = _fields(db)
        metadata = {
            k: validate_metadata(fields, k, v) for k, v in body.metadata.items() if v is not None
        }
        missing = _missing_required(fields, metadata)
        if missing:
            raise HTTPException(422, f"required metadata missing: {missing}")
        sample = Sample(sample_code=body.sample_code, metadata_=metadata)
        db.add(sample)
        db.flush()
        audit(
            db,
            user,
            "create",
            "sample",
            sample.id,
            {"sample_code": body.sample_code, "metadata": metadata},
        )
        return _sample_out(db, sample)


@router.get("/samples/{sample_id}", response_model=SampleOut)
def get_sample(sample_id: int, db: DB, user: CurrentUser) -> SampleOut:
    with db.begin():
        return _sample_out(db, _sample(db, sample_id))


@router.patch(
    "/samples/{sample_id}",
    response_model=SampleOut,
    summary="Edit sample metadata (merged; null removes a key)",
)
def patch_sample(sample_id: int, body: SamplePatch, db: DB, user: Editor) -> SampleOut:
    with db.begin():
        sample = _sample(db, sample_id)
        fields = _fields(db)
        changes: dict[str, Any] = {}
        if body.sample_code is not None and body.sample_code != sample.sample_code:
            changes["sample_code"] = {"old": sample.sample_code, "new": body.sample_code}
            sample.sample_code = body.sample_code
        if body.metadata:
            merged = dict(sample.metadata_)
            for key, value in body.metadata.items():
                new = None if value is None else validate_metadata(fields, key, value)
                if merged.get(key) != new:
                    changes[f"metadata.{key}"] = {"old": merged.get(key), "new": new}
                if new is None:
                    merged.pop(key, None)
                else:
                    merged[key] = new
            missing = _missing_required(fields, merged)
            if missing:
                raise HTTPException(422, f"required metadata missing: {missing}")
            sample.metadata_ = merged
        if changes:
            sample.updated_at = _now()
            audit(db, user, "update", "sample", sample.id, changes)
        db.flush()
        return _sample_out(db, sample)


@router.delete("/samples/{sample_id}", status_code=204, response_class=Response)
def delete_sample(sample_id: int, db: DB, user: Editor) -> Response:
    with db.begin():
        sample = _sample(db, sample_id)
        linked = (
            db.scalar(
                select(func.count()).select_from(SampleRun).where(SampleRun.sample_id == sample.id)
            )
            or 0
        )
        linked += (
            db.scalar(
                select(func.count())
                .select_from(OrderSample)
                .where(OrderSample.sample_id == sample.id)
            )
            or 0
        )
        if linked:
            raise HTTPException(409, "sample has results or orders")
        db.delete(sample)
        audit(db, user, "delete", "sample", sample_id, {"sample_code": sample.sample_code})
    return Response(status_code=204)


__all__ = ["order_ref", "router"]

"""Shared setup for API tests: an app on the per-test database, fixture data and users."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from qcdb.api.app import create_app
from qcdb.api.security import Settings, hash_password
from qcdb.db.models import AppUser, Owner, Run, Sample, SampleOrder, SampleRun
from qcdb.loader.core import LoadOptions, load_directory
from tests.conftest import FIXTURES

PASSWORDS = {
    "admin": "admin-password-123",
    "bioinformatician": "bioinf-password-123",
    "viewer": "viewer-password-123",
}
ROLES = ("admin", "bioinformatician", "viewer")


@dataclass
class Ids:
    values: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.values[key]


def load_all(sessions: sessionmaker[Session]) -> None:
    def run(directory: str, **options: Any) -> None:
        with sessions() as s:
            report = load_directory(
                s, LoadOptions(directory=FIXTURES / directory, invoked_by="test", **options)
            )
        assert report.exit_code == 0, report.lines()

    run("RUN_2606")
    run("RUN_2607", run_date=dt.date(2026, 7, 7))
    run("orders")
    run("metadata", metadata=FIXTURES / "metadata" / "metadata.csv")


def seed(sessions: sessionmaker[Session]) -> Ids:
    """Users for each role plus owners/orders/samples that the role matrix can modify."""
    with sessions() as s, s.begin():
        for role in ROLES:
            s.add(AppUser(username=role, role=role, password_hash=hash_password(PASSWORDS[role])))
        s.add(
            AppUser(
                username="target", role="viewer", password_hash=hash_password("target-password-123")
            )
        )
        owner = Owner(full_name="Anna Nowak", email="anna.nowak@example.org")
        owner_free = Owner(full_name="Piotr Wiśniewski", email="piotr@example.org")
        owner_erase = Owner(full_name="Maria Zielińska", email="maria@example.org")
        s.add_all([owner, owner_free, owner_erase])
        s.flush()
        order = s.scalar(select(SampleOrder).where(SampleOrder.order_code == "ZL/2026/001"))
        assert order is not None
        order.owner_id = owner.id
        empty_order = SampleOrder(order_code="ZL/2026/099")
        free_sample = Sample(sample_code="FREE_1", metadata_={})
        s.add_all([empty_order, free_sample])
        s.flush()

        def sr(run: str, code: str) -> int:
            row = s.scalar(
                select(SampleRun.id)
                .join(Run, Run.id == SampleRun.run_id)
                .where(Run.run_code == run, SampleRun.sample_code == code)
            )
            assert row is not None
            return row

        sample_5158 = s.scalar(select(Sample.id).where(Sample.sample_code == "260630_5158"))
        target = s.scalar(select(AppUser.id).where(AppUser.username == "target"))
        return Ids(
            {
                "owner_id": owner.id,
                "owner_free_id": owner_free.id,
                "owner_erase_id": owner_erase.id,
                "order_id": order.id,
                "order_empty_id": empty_order.id,
                "free_sample_id": free_sample.id,
                "sample_5158_id": sample_5158,
                "target_user_id": target,
                "sr_5156": sr("RUN_2606", "260630_5156"),
                "sr_5157": sr("RUN_2606", "260630_5157"),
                "sr_5158": sr("RUN_2606", "260630_5158"),
                "sr_5159": sr("RUN_2606", "260630_5159"),
                "sr_5156_r2": sr("RUN_2607", "260630_5156"),
            }
        )


class Client:
    """A logged-in test client that sends the CSRF header on unsafe requests."""

    def __init__(self, http: TestClient, csrf: str | None) -> None:
        self.http = http
        self.csrf = csrf

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}) or {})
        if self.csrf and method.upper() not in ("GET", "HEAD"):
            headers.setdefault("X-CSRF-Token", self.csrf)
        return self.http.request(method, url, headers=headers, **kwargs)

    def get(self, url: str, **kwargs: Any) -> Any:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return self.request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> Any:
        return self.request("PATCH", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Any:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Any:
        return self.request("DELETE", url, **kwargs)


class Api:
    def __init__(self, engine: Engine, settings: Settings | None = None) -> None:
        self.app = create_app(engine=engine, settings=settings or Settings())

    def anonymous(self) -> Client:
        return Client(TestClient(self.app, base_url="https://testserver"), None)

    def login(self, role: str, password: str | None = None) -> Client:
        http = TestClient(self.app, base_url="https://testserver")
        response = http.post(
            "/api/v1/auth/login", json={"username": role, "password": password or PASSWORDS[role]}
        )
        assert response.status_code == 200, response.text
        return Client(http, response.json()["csrf_token"])


@pytest.fixture
def api_env(engine: Engine, sessions: sessionmaker[Session]) -> tuple[Api, Ids]:
    load_all(sessions)
    ids = seed(sessions)
    return Api(engine), ids

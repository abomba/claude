"""Role matrix: every endpoint called as anonymous, viewer, bioinformatician and admin."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.routing import APIRoute

from tests.api_support import Api, Ids

READ = {"anonymous": 401, "viewer": 200, "bioinformatician": 200, "admin": 200}
EDIT_OK = {"anonymous": 401, "viewer": 403, "bioinformatician": 200, "admin": 200}
ADMIN_ONLY = {"anonymous": 401, "viewer": 403, "bioinformatician": 403, "admin": 200}
PUBLIC = {"anonymous": 200, "viewer": 200, "bioinformatician": 200, "admin": 200}


def codes(base: dict[str, int], ok: int) -> dict[str, int]:
    return {role: (ok if code == 200 else code) for role, code in base.items()}


# (method, path template, json body, expected status per role). Order matters: entities are
# created before they are changed or deleted. Paths use ids from tests.api_support.seed.
MATRIX: list[tuple[str, str, Any, dict[str, int]]] = [
    ("GET", "/api/v1/health", None, PUBLIC),
    ("GET", "/api/v1/health/ready", None, PUBLIC),
    (
        "POST",
        "/api/v1/auth/login",
        {"username": "nobody", "password": "wrong-password"},
        {"anonymous": 401, "viewer": 401, "bioinformatician": 401, "admin": 401},
    ),
    ("GET", "/api/v1/auth/me", None, READ),
    ("GET", "/api/v1/results?verdict=PASS&sort=-raw_reads", None, READ),
    ("GET", "/api/v1/results/export.csv", None, READ),
    ("GET", "/api/v1/results/{sr_5157}", None, READ),
    ("GET", "/api/v1/results/{sr_5157}/versions", None, READ),
    ("GET", "/api/v1/results/{sr_5157}/versions/1", None, READ),
    ("POST", "/api/v1/results/{sr_5157}/current", {"version_no": 1}, EDIT_OK),
    ("PUT", "/api/v1/results/{sr_5156_r2}/sample", {"sample_id": "{sample_5158_id}"}, EDIT_OK),
    ("GET", "/api/v1/runs", None, READ),
    ("GET", "/api/v1/runs/RUN_2606", None, READ),
    ("PATCH", "/api/v1/runs/RUN_2607", {"run_date": "2026-07-08"}, EDIT_OK),
    ("GET", "/api/v1/runs/RUN_2606/outliers", None, READ),
    ("GET", "/api/v1/metrics", None, READ),
    ("GET", "/api/v1/trends?metric=fastp.pct_q30_after_filter", None, READ),
    ("GET", "/api/v1/owners", None, READ),
    ("POST", "/api/v1/owners", {"full_name": "Nowy Zleceniodawca"}, codes(EDIT_OK, 201)),
    ("GET", "/api/v1/owners/{owner_id}", None, READ),
    ("PATCH", "/api/v1/owners/{owner_id}", {"email": "anna@example.org"}, EDIT_OK),
    ("DELETE", "/api/v1/owners/{owner_free_id}", None, codes(EDIT_OK, 204)),
    ("POST", "/api/v1/owners/{owner_erase_id}/erase", None, ADMIN_ONLY),
    ("GET", "/api/v1/orders", None, READ),
    (
        "POST",
        "/api/v1/orders",
        {"order_code": "ZL/2026/100", "owner_id": "{owner_id}"},
        codes(EDIT_OK, 201),
    ),
    ("GET", "/api/v1/orders/{order_id}", None, READ),
    ("PATCH", "/api/v1/orders/{order_id}", {"owner_id": "{owner_id}"}, EDIT_OK),
    ("POST", "/api/v1/orders/{order_id}/samples", {"sample_ids": ["{free_sample_id}"]}, EDIT_OK),
    ("DELETE", "/api/v1/orders/{order_id}/samples/{free_sample_id}", None, codes(EDIT_OK, 204)),
    ("DELETE", "/api/v1/orders/{order_empty_id}", None, codes(EDIT_OK, 204)),
    ("GET", "/api/v1/sample-fields", None, READ),
    (
        "POST",
        "/api/v1/sample-fields",
        {"key": "project", "label": "Projekt", "data_type": "choice", "choices": ["A", "B"]},
        codes(ADMIN_ONLY, 201),
    ),
    (
        "PATCH",
        "/api/v1/sample-fields/material_type",
        {"label": "Rodzaj materiału (izolat)"},
        ADMIN_ONLY,
    ),
    ("GET", "/api/v1/samples", None, READ),
    (
        "POST",
        "/api/v1/samples",
        {"sample_code": "NEW_1", "metadata": {"material_type": "wymaz"}},
        codes(EDIT_OK, 201),
    ),
    ("GET", "/api/v1/samples/{free_sample_id}", None, READ),
    (
        "PATCH",
        "/api/v1/samples/{free_sample_id}",
        {"metadata": {"collection_date": "2026-06-01"}},
        EDIT_OK,
    ),
    ("DELETE", "/api/v1/samples/{free_sample_id}", None, codes(EDIT_OK, 204)),
    ("GET", "/api/v1/users", None, ADMIN_ONLY),
    (
        "POST",
        "/api/v1/users",
        {"username": "new_user", "role": "viewer", "password": "new-user-password-1"},
        codes(ADMIN_ONLY, 201),
    ),
    ("PATCH", "/api/v1/users/{target_user_id}", {"role": "bioinformatician"}, ADMIN_ONLY),
    (
        "POST",
        "/api/v1/users/{target_user_id}/password",
        {"password": "another-password-1"},
        codes(ADMIN_ONLY, 204),
    ),
    ("GET", "/api/v1/audit", None, ADMIN_ONLY),
    ("POST", "/api/v1/auth/logout", None, codes(READ, 204)),
]


def _fill(value: Any, ids: Ids) -> Any:
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        return ids[value[1:-1]]
    if isinstance(value, str):
        return value.format(**ids.values)
    if isinstance(value, dict):
        return {k: _fill(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, ids) for v in value]
    return value


def test_matrix_covers_every_endpoint(api_env: tuple[Api, Ids]) -> None:
    api, _ = api_env
    routes = {
        (method, route.path)
        for route in api.app.routes
        if isinstance(route, APIRoute)
        for method in route.methods or ()
    }
    covered = set()
    for method, path, _, _ in MATRIX:
        template = path.split("?")[0]
        for route_method, route_path in routes:
            pattern = route_path.replace("{", "<").replace("}", ">")
            parts, tparts = pattern.split("/"), template.split("/")
            if (
                route_method == method
                and len(parts) == len(tparts)
                and all(a == b or a.startswith("<") for a, b in zip(parts, tparts, strict=True))
            ):
                covered.add((route_method, route_path))
    assert routes - covered == set(), "add new endpoints to MATRIX"


@pytest.mark.parametrize("role", ["anonymous", "viewer", "bioinformatician", "admin"])
def test_role_matrix(api_env: tuple[Api, Ids], role: str) -> None:
    api, ids = api_env
    client = api.anonymous() if role == "anonymous" else api.login(role)
    failures = []
    for method, path, body, expected in MATRIX:
        url = _fill(path, ids)
        response = client.request(method, url, json=_fill(body, ids) if body is not None else None)
        if response.status_code != expected[role]:
            failures.append(
                f"{method} {url}: {response.status_code} != {expected[role]} "
                f"({response.text[:120]})"
            )
    assert failures == []

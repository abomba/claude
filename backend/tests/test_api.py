"""API integration tests on real PostgreSQL (data loaded with the real loader)."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from qcdb.api.common import mask_paths
from qcdb.api.security import Settings
from qcdb.db.models import AuditLog, Owner, UserSession
from qcdb.jsonio import loads_exact
from tests.api_support import PASSWORDS, Api, Ids
from tests.conftest import FIXTURES, Loader

R = "/api/v1/results"


def qc(sample: str, run: str = "RUN_2606") -> Any:
    return loads_exact((FIXTURES / run / f"{sample}.qc.json").read_bytes())


# ---------------------------------------------------------------------- auth and sessions
def test_login_cookie_flags(api_env: tuple[Api, Ids]) -> None:
    api, _ = api_env
    http = api.anonymous().http
    response = http.post(
        "/api/v1/auth/login", json={"username": "viewer", "password": PASSWORDS["viewer"]}
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert "path=/api" in cookie
    assert response.json()["role"] == "viewer"


def test_wrong_password_and_lockout(api_env: tuple[Api, Ids]) -> None:
    api, _ = api_env
    http = api.anonymous().http
    for _ in range(5):
        r = http.post("/api/v1/auth/login", json={"username": "viewer", "password": "nope-nope"})
        assert r.status_code == 401
        assert r.json()["detail"] == "invalid username or password"
    r = http.post(
        "/api/v1/auth/login", json={"username": "viewer", "password": PASSWORDS["viewer"]}
    )
    assert r.status_code == 401, "account is locked after 5 failures"
    unknown = http.post("/api/v1/auth/login", json={"username": "ghost", "password": "x" * 12})
    assert unknown.json() == r.json(), "no difference between unknown and locked users"


def test_csrf_required(api_env: tuple[Api, Ids]) -> None:
    api, ids = api_env
    client = api.login("bioinformatician")
    url = f"/api/v1/owners/{ids['owner_id']}"
    assert client.http.patch(url, json={"email": "a@b.cd"}).status_code == 403
    assert (
        client.http.patch(
            url, json={"email": "a@b.cd"}, headers={"X-CSRF-Token": "forged"}
        ).status_code
        == 403
    )
    assert client.patch(url, json={"email": "a@b.cd"}).status_code == 200


def test_logout_and_expired_session(
    api_env: tuple[Api, Ids], sessions: sessionmaker[Session]
) -> None:
    api, _ = api_env
    client = api.login("viewer")
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    client = api.login("viewer")
    with sessions() as s, s.begin():
        for row in s.scalars(select(UserSession)):
            row.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_deactivated_user_loses_access(api_env: tuple[Api, Ids]) -> None:
    api, ids = api_env
    target = api.login("target", "target-password-123")
    admin = api.login("admin")
    assert (
        admin.patch(f"/api/v1/users/{ids['target_user_id']}", json={"is_active": False}).status_code
        == 200
    )
    assert target.get("/api/v1/auth/me").status_code == 401
    assert (
        admin.patch(f"/api/v1/users/{ids['target_user_id']}", json={"is_active": True}).status_code
        == 200
    )
    me = admin.get("/api/v1/auth/me").json()
    assert admin.patch(f"/api/v1/users/{me['id']}", json={"role": "viewer"}).status_code == 409


# ---------------------------------------------------------------------- personal data
def test_viewer_gets_no_contact_details(api_env: tuple[Api, Ids]) -> None:
    api, ids = api_env
    viewer, bio = api.login("viewer"), api.login("bioinformatician")
    v_list = viewer.get("/api/v1/owners").json()["items"]
    b_list = bio.get("/api/v1/owners").json()["items"]
    assert all("email" not in o for o in v_list)
    assert any(o.get("email") == "anna.nowak@example.org" for o in b_list)
    v_one = viewer.get(f"/api/v1/owners/{ids['owner_id']}").json()
    assert "email" not in v_one and v_one["full_name"] == "Anna Nowak"
    assert "example.org" not in viewer.get(f"{R}/export.csv").text
    assert "example.org" not in json.dumps(viewer.get(f"/api/v1/orders/{ids['order_id']}").json())


def test_viewer_gets_no_technical_data(api_env: tuple[Api, Ids]) -> None:
    api, ids = api_env
    viewer, bio = api.login("viewer"), api.login("bioinformatician")
    v = viewer.get(f"{R}/{ids['sr_5156']}").json()
    b = bio.get(f"{R}/{ids['sr_5156']}").json()
    assert "technical" not in v["version"] and "technical" in b["version"]
    text_v = json.dumps(v)
    for secret in (
        "/mnt/ngs_data",
        "fq/trim",
        "qc_thresholds.yml",
        "Jan Kowalski",
        "260630_5156.fastp.metrics.json",
    ):
        assert secret not in text_v, secret
    assert "/mnt/ngs_data/sylph_db/globdb_r226_sylph_tax.tsv" in json.dumps(b)
    sylph_v = next(t for t in v["version"]["tools"] if t["tool"] == "sylph")
    assert "sylph.taxonomies_used" not in {m["key"] for m in sylph_v["metrics"]}
    assert "sylph.taxonomies_used" not in sylph_v["absent_metrics"]
    order_v = viewer.get(f"/api/v1/orders/{ids['order_id']}").json()
    assert "meta" not in order_v
    assert bio.get(f"/api/v1/orders/{ids['order_id']}").json()["meta"] == {
        "Zleceniodawca": "Jan Kowalski"
    }


def test_path_masking() -> None:
    assert mask_paths("cannot open /mnt/ngs_data/db/x.tsv: missing") == "cannot open x.tsv: missing"
    assert mask_paths("read fq/trim/S3_L001_R1_001.fastq.gz") == "read S3_L001_R1_001.fastq.gz"
    assert mask_paths("serotype 4:i:1,2 and O157:H7") == "serotype 4:i:1,2 and O157:H7"


def test_owner_erasure_keeps_results_and_audit_has_no_values(
    api_env: tuple[Api, Ids], sessions: sessionmaker[Session], engine: Engine
) -> None:
    api, ids = api_env
    admin = api.login("admin")
    assert (
        admin.patch(
            f"/api/v1/owners/{ids['owner_id']}", json={"email": "nowy@example.org"}
        ).status_code
        == 200
    )
    r = admin.post(f"/api/v1/owners/{ids['owner_id']}/erase")
    assert r.status_code == 200
    assert r.json()["full_name"] is None and r.json()["erased"] is True
    assert r.json()["email"] is None
    order = admin.get(f"/api/v1/orders/{ids['order_id']}").json()
    assert order["owner"]["erased"] is True and order["n_samples"] == 2
    with engine.connect() as conn:
        audit = " ".join(r[0] for r in conn.execute(text("SELECT changes::text FROM audit_log")))
    for personal in ("Anna", "Nowak", "nowy@example.org", "anna.nowak"):
        assert personal not in audit
    assert (
        admin.patch(f"/api/v1/owners/{ids['owner_id']}", json={"full_name": "X"}).status_code == 409
    )
    with sessions() as s:
        owner = s.get(Owner, ids["owner_id"])
        assert owner is not None and owner.email is None and owner.erased_at is not None


# ---------------------------------------------------------------------- results
def test_sample_table_filters_and_pagination(api_env: tuple[Api, Ids]) -> None:
    api, ids = api_env
    c = api.login("viewer")

    def codes(query: str) -> list[tuple[str, str]]:
        body = c.get(f"{R}?page_size=500&{query}").json()
        return sorted((i["run_code"], i["sample_code"]) for i in body["items"])

    assert len(codes("")) == 6
    assert codes("verdict=WARN") == [("RUN_2606", "260630_5157")]
    assert codes("verdict=none") == [("RUN_2606", "260630_5159"), ("RUN_2606", "260630_5160")]
    assert codes("species=Escherichia%20coli") == [("RUN_2606", "260630_5158")]
    assert codes("run=RUN_2607") == [("RUN_2607", "260630_5156")]
    assert codes(f"owner_id={ids['owner_id']}") == [
        ("RUN_2606", "260630_5156"),
        ("RUN_2606", "260630_5157"),
        ("RUN_2607", "260630_5156"),
    ]
    assert codes("q=5158") == [("RUN_2606", "260630_5158")]
    assert codes("q=ZL/2026/002") == [("RUN_2606", "260630_5158")]
    assert codes("date_from=2026-07-01") == [("RUN_2607", "260630_5156")]
    assert codes("amr_gene=blaTEM-1") == [("RUN_2606", "260630_5156")]
    assert codes("amr_class=quinolone") == [("RUN_2606", "260630_5156")]
    assert codes("composition_species=Klebsiella%20pneumoniae&composition_min_pct=2") == [
        ("RUN_2606", "260630_5158")
    ]
    assert codes("composition_species=Klebsiella%20pneumoniae&composition_min_pct=5") == []
    page = c.get(f"{R}?page=2&page_size=4&sort=sample_code").json()
    assert page["total"] == 6 and len(page["items"]) == 2 and page["page"] == 2
    assert c.get(f"{R}?sort=password").status_code == 422
    assert c.get(f"{R}?verdict=MAYBE").status_code == 422
    first = c.get(f"{R}?run=RUN_2606&sort=-raw_reads").json()["items"][0]
    assert first["sample_code"] == "260630_5158"
    row = next(
        i for i in c.get(f"{R}?run=RUN_2606").json()["items"] if i["sample_code"] == "260630_5156"
    )
    assert row["raw_reads"] == 2857664 and row["depth"] == 74.9057
    assert row["orders"][0]["order_code"] == "ZL/2026/001"


@pytest.mark.parametrize("sample", ["260630_5156", "260630_5157", "260630_5158"])
def test_detail_verdict_and_checks_match_qc_json(api_env: tuple[Api, Ids], sample: str) -> None:
    api, ids = api_env
    doc = qc(sample)
    detail = api.login("viewer").get(f"{R}/{ids['sr_' + sample[-4:]]}").json()
    version = detail["version"]
    assert version["verdict"] == doc["verdict"]
    assert version["thresholds"]["sha256"] == doc["thresholds"]["sha256"]
    assert version["thresholds"]["chain"] == doc["thresholds"]["chain"]
    assert [
        (c["metric"], c["status"], c["reason"], c["rule"], c["required"]) for c in version["checks"]
    ] == [
        (
            c["metric"],
            c["status"],
            c["reason"],
            json.loads(json.dumps(c["rule"], default=float)),
            c["required"],
        )
        for c in doc["checks"]
    ]
    for got, want in zip(version["checks"], doc["checks"], strict=True):
        if isinstance(want["value"], str) or want["value"] is None:
            assert got["value"] == want["value"]
        else:
            assert Decimal(str(got["value"])) == want["value"]
    assert version["reasons"] == doc["reasons"]


def test_detail_metrics_statuses_typing(api_env: tuple[Api, Ids]) -> None:
    api, ids = api_env
    c = api.login("viewer")
    d = c.get(f"{R}/{ids['sr_5157']}").json()["version"]
    tools = {t["tool"]: t for t in d["tools"]}
    assert tools["kraken2"]["status"] == "missing" and tools["kraken2"]["metrics"] == []
    mlst = {m["key"]: m for m in tools["mlst"]["metrics"]}
    assert mlst["mlst.sequence_type"]["is_null"] is True
    assert "fastp.pct_duplication" in tools["fastp"]["absent_metrics"]
    assert [t["namespace"] for t in d["tools"]] == sorted(
        [t["namespace"] for t in d["tools"]],
        key=["reads", "composition", "assembly", "characterisation"].index,
    )
    d6 = c.get(f"{R}/{ids['sr_5156']}").json()
    v6 = d6["version"]
    assert v6["typing"]["mlst_sequence_type"] == "19"
    assert v6["typing"]["seqsero2_serotype"] == "Typhimurium"
    assert v6["amr_hits"][0]["symbol"] == "blaTEM-1" and "class" in v6["amr_hits"][0]
    assert v6["software"]["pipeline"] == "dnw/vistula"
    assert d6["sample"]["metadata"]["material_type"] == "izolat"
    d8 = c.get(f"{R}/{ids['sr_5158']}").json()["version"]
    assert d8["typing"]["ectyper_qc_flag"] == "PASS (REPORTABLE)" and d8["verdict"] == "FAIL"
    contamination = next(
        m
        for t in d8["tools"]
        if t["tool"] == "checkm2"
        for m in t["metrics"]
        if m["key"] == "checkm2.pct_contamination"
    )
    assert contamination["value"] == 112.5
    no_results = c.get(f"{R}/{ids['sr_5159']}").json()
    assert no_results["version"] is None and no_results["n_versions"] == 0
    assert c.get(f"{R}/999999").status_code == 404


def test_versions_and_set_current(api_env: tuple[Api, Ids], run_dir: Path, load: Loader) -> None:
    api, ids = api_env
    path = run_dir / "260630_5157.qc.json"
    doc = json.loads(path.read_text())
    doc["verdict"] = "FAIL"
    doc["checks"][1].update({"status": "FAIL", "reason": "81 < 85 (reprocessed)"})
    path.write_text(json.dumps(doc))
    assert load(run_dir).exit_code == 0
    bio = api.login("bioinformatician")
    versions = bio.get(f"{R}/{ids['sr_5157']}/versions").json()
    assert [(v["version_no"], v["verdict"], v["is_current"]) for v in versions] == [
        (1, "WARN", False),
        (2, "FAIL", True),
    ]
    assert versions[1]["check_changes"] == [
        {"metric": "fastp.pct_q30_before_filter", "old_status": "WARN", "new_status": "FAIL"}
    ]
    old = bio.get(f"{R}/{ids['sr_5157']}/versions/1").json()["version"]
    assert old["verdict"] == "WARN" and old["is_current"] is False
    r = bio.post(f"{R}/{ids['sr_5157']}/current", json={"version_no": 1})
    assert r.status_code == 200 and r.json()["version"]["version_no"] == 1
    table = bio.get(f"{R}?q=5157").json()["items"][0]
    assert table["verdict"] == "WARN" and table["n_versions"] == 2  # view refreshed
    assert bio.post(f"{R}/{ids['sr_5157']}/current", json={"version_no": 9}).status_code == 404


def test_relink_result_to_other_sample(api_env: tuple[Api, Ids]) -> None:
    api, ids = api_env
    bio = api.login("bioinformatician")
    r = bio.put(f"{R}/{ids['sr_5156_r2']}/sample", json={"sample_id": ids["free_sample_id"]})
    assert r.status_code == 200 and r.json()["sample"]["sample_code"] == "FREE_1"
    sample = bio.get(f"/api/v1/samples/{ids['free_sample_id']}").json()
    assert [x["run_code"] for x in sample["results"]] == ["RUN_2607"]
    assert bio.put(f"{R}/{ids['sr_5156_r2']}/sample", json={"sample_id": 10**9}).status_code == 404


def test_csv_export(api_env: tuple[Api, Ids]) -> None:
    api, _ = api_env
    c = api.login("viewer")
    r = c.get(f"{R}/export.csv?run=RUN_2606&sort=sample_code")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:4] == ["sample_code", "run_code", "run_date", "verdict"]
    assert rows[1][0] == "Próbka" and "Odczyty (surowe) [reads]" in rows[1]
    body = {row[0]: dict(zip(rows[0], row, strict=True)) for row in rows[2:]}
    assert list(body) == ["260630_5156", "260630_5157", "260630_5158", "260630_5159", "260630_5160"]
    assert body["260630_5156"]["raw_reads"] == "2857664"
    assert body["260630_5156"]["raw_q30"] == "87.7232"
    assert body["260630_5156"]["owners"] == "Anna Nowak"
    assert body["260630_5159"]["verdict"] == ""


def test_csv_formula_injection_escaped() -> None:
    from qcdb.api.common import csv_text

    out = csv_text(["a", "b"], ["A", "B"], [["=HYPERLINK(1)", -5]])
    assert out.splitlines()[2] == "'=HYPERLINK(1),-5"


# ---------------------------------------------------------------------- runs, trends
def test_runs(api_env: tuple[Api, Ids]) -> None:
    api, _ = api_env
    c = api.login("viewer")
    runs = {r["run_code"]: r for r in c.get("/api/v1/runs").json()["items"]}
    assert (
        runs["RUN_2606"]["n_pass"],
        runs["RUN_2606"]["n_warn"],
        runs["RUN_2606"]["n_fail"],
        runs["RUN_2606"]["n_missing"],
        runs["RUN_2606"]["n_samples"],
    ) == (1, 1, 1, 2, 5)
    assert runs["RUN_2606"]["run_date"] == "2026-06-30"
    detail = c.get("/api/v1/runs/RUN_2606").json()
    assert detail["summary_matches_run_document"] is True
    assert c.get("/api/v1/runs/RUN_2607").json()["run_document_summary"] is None
    bio = api.login("bioinformatician")
    r = bio.patch("/api/v1/runs/RUN_2607", json={"run_date": "2026-07-09"})
    assert r.json()["run_date"] == "2026-07-09" and r.json()["run_date_source"] == "ui"
    item = bio.get(f"{R}?run=RUN_2607").json()["items"][0]
    assert item["run_date"] == "2026-07-09"
    assert c.get("/api/v1/runs/NOPE").status_code == 404


def test_outliers(api_env: tuple[Api, Ids], tmp_path: Path, load: Loader) -> None:
    api, _ = api_env
    source = loads_exact((FIXTURES / "RUN_2606" / "260630_5160.fastp.metrics.json").read_bytes())
    from qcdb.jsonio import dumps_exact

    for i, pairs in enumerate([400000, 401000, 402000, 403000, 404000, 3000000]):
        doc = json.loads(dumps_exact(source), parse_float=Decimal)
        doc["sample_id"] = f"OUT_{i}"
        doc["metrics"]["read_pairs_before_filter"]["value"] = pairs
        (tmp_path / f"OUT_{i}.fastp.metrics.json").write_text(dumps_exact(doc))
    assert load(tmp_path, run_id="RUN_OUT").exit_code == 0
    out = api.login("viewer").get("/api/v1/runs/RUN_OUT/outliers").json()
    assert [(o["column"], o["sample_code"], o["direction"]) for o in out] == [
        ("raw_reads", "OUT_5", "high")
    ]


def test_metrics_and_trends(api_env: tuple[Api, Ids]) -> None:
    api, _ = api_env
    c = api.login("viewer")
    metrics = {m["key"]: m for m in c.get("/api/v1/metrics").json()}
    assert len([m for m in metrics.values() if m["source"] == "dictionary"]) == 140
    assert metrics["fastp.insert_size_peak"]["value_type"] == "float"
    assert metrics["derived.depth"]["source"] == "check"
    assert metrics["mlst.sequence_type"]["numeric"] is False
    t = c.get("/api/v1/trends?metric=fastp.pct_q30_after_filter&group_by=run").json()
    assert t["unit"] == "percent"
    assert [(p["run_code"], p["sample_code"]) for p in t["points"]] == [
        ("RUN_2606", "260630_5156"),
        ("RUN_2606", "260630_5157"),
        ("RUN_2606", "260630_5158"),
        ("RUN_2606", "260630_5160"),
        ("RUN_2607", "260630_5156"),
    ]
    assert t["points"][3]["verdict"] is None  # metrics-only result: a point without a verdict
    assert t["threshold_changes"][0]["run_code"] == "RUN_2607"
    assert {g["key"]: g["n"] for g in t["groups"]} == {"RUN_2606": 4, "RUN_2607": 1}
    assert t["excluded_without_date"] == 0
    depth = c.get("/api/v1/trends?metric=derived.depth&species=Escherichia%20coli").json()
    assert [p["sample_code"] for p in depth["points"]] == ["260630_5158"]
    assert c.get("/api/v1/trends?metric=mlst.sequence_type").status_code == 404


# ---------------------------------------------------------------------- owners, orders, samples
def test_order_assignment_flow(api_env: tuple[Api, Ids], sessions: sessionmaker[Session]) -> None:
    api, ids = api_env
    bio = api.login("bioinformatician")
    owner = bio.post(
        "/api/v1/owners", json={"full_name": "Ewa Lis", "email": "ewa@example.org"}
    ).json()
    order = bio.post(
        "/api/v1/orders", json={"order_code": "ZL/2026/200", "owner_id": owner["id"]}
    ).json()
    assert bio.post("/api/v1/orders", json={"order_code": "ZL/2026/200"}).status_code == 409
    r = bio.post(
        f"/api/v1/orders/{order['id']}/samples", json={"sample_ids": [ids["sample_5158_id"]]}
    )
    assert r.status_code == 200 and [s["sample_code"] for s in r.json()["samples"]] == [
        "260630_5158"
    ]
    table = bio.get(f"{R}?owner_id={owner['id']}").json()["items"]
    assert [i["sample_code"] for i in table] == ["260630_5158"]
    assert {o["order_code"] for o in table[0]["orders"]} == {"ZL/2026/002", "ZL/2026/200"}
    assert (
        bio.post("/api/v1/owners", json={"full_name": "X", "email": "not-an-email"}).status_code
        == 422
    )
    assert bio.delete(f"/api/v1/orders/{order['id']}").status_code == 409
    with sessions() as s:
        entries = s.scalars(
            select(AuditLog.action).where(
                AuditLog.entity_type == "sample_order", AuditLog.entity_id == str(order["id"])
            )
        )
        assert set(entries) == {"create", "link"}


def test_sample_metadata_validation(api_env: tuple[Api, Ids]) -> None:
    api, ids = api_env
    admin = api.login("admin")
    url = f"/api/v1/samples/{ids['free_sample_id']}"
    assert admin.patch(url, json={"metadata": {"collection_date": "30.06.2026"}}).status_code == 422
    assert admin.patch(url, json={"metadata": {"pesel": "1"}}).status_code == 422
    assert (
        admin.post(
            "/api/v1/sample-fields",
            json={
                "key": "project",
                "label": "Projekt",
                "data_type": "choice",
                "choices": ["A", "B"],
                "required": True,
            },
        ).status_code
        == 201
    )
    assert admin.patch(url, json={"metadata": {"material_type": "x"}}).status_code == 422
    r = admin.patch(url, json={"metadata": {"project": "A", "material_type": "izolat"}})
    assert r.status_code == 200 and r.json()["metadata"] == {
        "project": "A",
        "material_type": "izolat",
    }
    assert admin.patch(url, json={"metadata": {"project": "C"}}).status_code == 422
    other = admin.get(f"/api/v1/samples/{ids['sample_5158_id']}").json()
    assert other["missing_required"] == ["project"]
    assert (
        admin.patch("/api/v1/sample-fields/project", json={"is_active": False}).status_code == 200
    )
    assert admin.get(f"/api/v1/samples/{ids['sample_5158_id']}").json()["missing_required"] == []


def test_audit_log(api_env: tuple[Api, Ids]) -> None:
    api, _ = api_env
    admin = api.login("admin")
    admin.patch("/api/v1/runs/RUN_2607", json={"run_date": "2026-07-10"})
    entries = admin.get("/api/v1/audit?entity_type=run&entity_id=RUN_2607").json()["items"]
    assert entries[0]["actor_label"] == "admin"
    assert entries[0]["changes"]["run_date"]["new"] == "2026-07-10"
    assert any(e["actor_label"] == "loader:test" for e in entries)


# ---------------------------------------------------------------------- service
def test_health_ready(api_env: tuple[Api, Ids]) -> None:
    api, _ = api_env
    r = api.anonymous().get("/api/v1/health/ready")
    assert r.status_code == 200 and r.json()["migration"] == "0001"


def test_openapi_document_is_up_to_date() -> None:
    from qcdb.api.openapi import openapi_document

    committed = json.loads((Path(__file__).parents[1] / "openapi.json").read_text())
    assert openapi_document() == committed, "run: python -m qcdb.api.openapi > openapi.json"


def test_insecure_cookie_setting(engine: Engine, sessions: sessionmaker[Session]) -> None:
    from qcdb.api.security import hash_password
    from qcdb.db.models import AppUser

    with sessions() as s, s.begin():
        s.add(AppUser(username="dev", role="viewer", password_hash=hash_password("x" * 12)))
    api = Api(engine, Settings(cookie_secure=False))
    r = api.anonymous().http.post(
        "/api/v1/auth/login", json={"username": "dev", "password": "x" * 12}
    )
    assert r.status_code == 200 and "secure" not in r.headers["set-cookie"].lower()

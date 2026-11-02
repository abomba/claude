"""The ``qcdb`` command: exit codes and credentials handling."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.engine import URL

from qcdb.cli import main
from qcdb.config import masked
from tests.conftest import FIXTURES


@pytest.fixture
def env(db_url: URL, monkeypatch: pytest.MonkeyPatch) -> URL:
    monkeypatch.setenv("QCDB_DATABASE_URL", db_url.render_as_string(hide_password=False))
    monkeypatch.setenv("QCDB_INVOKED_BY", "pytest")
    return db_url


def test_load_exit_codes(env: URL, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["load", str(FIXTURES / "RUN_2606")]) == 0
    out = capsys.readouterr().out
    assert "new versions 4" in out
    assert main(["load", str(FIXTURES / "RUN_2606")]) == 0
    assert "unchanged 4" in capsys.readouterr().out
    assert main(["load", str(tmp_path / "missing")]) == 2
    with pytest.raises(SystemExit) as exc:
        main(["load", str(FIXTURES / "RUN_2606"), "--run-date", "30.06.2026"])
    assert exc.value.code == 2
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "x.qc.json").write_text("[", encoding="utf-8")
    assert main(["load", str(bad)]) == 3


def test_import_dictionary_cli(
    env: URL, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from qcdb.dictionary import default_dictionary_path

    assert main(["import-dictionary", str(default_dictionary_path())]) == 0
    assert "already imported" in capsys.readouterr().out
    broken = tmp_path / "broken.psv"
    broken.write_text("not|a|dictionary\n", encoding="utf-8")
    assert main(["import-dictionary", str(broken)]) == 3
    assert main(["import-dictionary", str(tmp_path / "none.psv")]) == 2


def test_no_database_configured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for var in ("QCDB_DATABASE_URL", "PGHOST"):
        monkeypatch.delenv(var, raising=False)
    assert main(["load", str(FIXTURES / "RUN_2606")]) == 2
    assert "QCDB_DATABASE_URL" in capsys.readouterr().err


def test_password_never_printed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(
        "QCDB_DATABASE_URL", "postgresql://qcdb:s3cret-pw@127.0.0.1:1/qcdb?connect_timeout=1"
    )
    assert main(["load", str(FIXTURES / "RUN_2606")]) == 2
    captured = capsys.readouterr()
    assert "s3cret-pw" not in captured.out + captured.err
    assert "***" in captured.err
    assert "s3cret" not in masked("postgresql://u:s3cret@h/db")


def test_password_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from qcdb.config import database_url

    secret = tmp_path / "pw"
    secret.write_text("from-file\n", encoding="utf-8")
    monkeypatch.setenv("QCDB_DATABASE_URL", "postgresql://qcdb@db/qcdb")
    monkeypatch.setenv("QCDB_DATABASE_PASSWORD_FILE", str(secret))
    assert database_url().password == "from-file"

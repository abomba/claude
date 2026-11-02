"""The committed fixture files are exactly what tests/fixtures/build.py generates."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests.conftest import FIXTURES


def test_fixtures_up_to_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "fixture_build", Path(__file__).parent / "fixtures" / "build.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "OUT", tmp_path)
    module.main()
    generated = {
        p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }
    committed = {
        p.relative_to(FIXTURES): p.read_bytes() for p in FIXTURES.rglob("*") if p.is_file()
    }
    assert generated.keys() == committed.keys()
    stale = [str(k) for k in generated if generated[k] != committed[k]]
    assert stale == [], "run: python tests/fixtures/build.py"

"""Find and read input files: documents by suffix, samplesheets by name."""

from __future__ import annotations

import csv
import io
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qcdb.jsonio import JsonFormatError, loads_exact, sha256_hex

SUFFIXES: tuple[tuple[str, str], ...] = (
    (".metrics.json", "metrics"),
    (".qc.json", "qc"),
    (".report.json", "report"),
    (".run.json", "run"),
    (".order.json", "order"),
)
SAMPLESHEET_RE = re.compile(r"^samplesheet.*\.(csv|tsv)$", re.IGNORECASE)
PER_SAMPLE_KINDS = ("metrics", "qc", "report")


@dataclass
class Document:
    path: Path
    kind: str
    raw: bytes
    sha256: str
    content: Any

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class SamplesheetRow:
    sample_id: str
    run_id: str | None


@dataclass
class Samplesheet:
    path: Path
    sha256: str
    rows: list[SamplesheetRow]


@dataclass
class Unreadable:
    path: Path
    message: str
    sample_hint: str | None  # sample_id derived from the file name, for per-sample documents


@dataclass
class ScanResult:
    documents: list[Document] = field(default_factory=list)
    samplesheets: list[Samplesheet] = field(default_factory=list)
    unreadable: list[Unreadable] = field(default_factory=list)
    ignored: int = 0


def classify(name: str) -> str | None:
    for suffix, kind in SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return kind
    if SAMPLESHEET_RE.match(name):
        return "samplesheet"
    return None


def sample_hint(name: str, kind: str) -> str | None:
    """``S1.fastp.metrics.json`` -> ``S1``; ``S1.qc.json`` -> ``S1``. Content always wins."""
    for suffix, k in SUFFIXES:
        if k == kind and name.endswith(suffix):
            stem = name[: -len(suffix)]
            if kind == "metrics":
                return stem.rsplit(".", 1)[0] if "." in stem else None
            return stem if kind in PER_SAMPLE_KINDS else None
    return None


def _walk(root: Path) -> list[Path]:
    """All regular files under ``root``, following symlinks without looping."""
    found: list[Path] = []
    seen_dirs: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if real in seen_dirs:
            dirnames[:] = []
            continue
        seen_dirs.add(real)
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_file():
                found.append(path)
    return found


def parse_samplesheet(path: Path, raw: bytes) -> list[SamplesheetRow]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("not valid UTF-8") from None
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter, strict=True)
    try:
        header = reader.fieldnames or []
        id_column = next((c for c in ("sample_id", "sample") if c in header), None)
        if id_column is None:
            raise ValueError("no 'sample' or 'sample_id' column")
        rows: list[SamplesheetRow] = []
        for line_no, record in enumerate(reader, start=2):
            sample_id = (record.get(id_column) or "").strip()
            if not sample_id:
                raise ValueError(f"line {line_no}: empty sample id")
            run_id = (record.get("run_id") or "").strip() or None
            rows.append(SamplesheetRow(sample_id, run_id))
    except csv.Error as exc:
        raise ValueError(f"CSV error: {exc}") from None
    return rows


def scan(root: Path) -> ScanResult:
    result = ScanResult()
    seen_sha: set[str] = set()
    for path in _walk(root):
        kind = classify(path.name)
        if kind is None:
            result.ignored += 1
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            result.unreadable.append(Unreadable(path, f"cannot read: {exc.strerror}", None))
            continue
        sha = sha256_hex(raw)
        if sha in seen_sha:  # the same bytes reached twice (copy or symlink): load once
            continue
        seen_sha.add(sha)
        if kind == "samplesheet":
            try:
                result.samplesheets.append(Samplesheet(path, sha, parse_samplesheet(path, raw)))
            except ValueError as exc:
                result.unreadable.append(Unreadable(path, f"unreadable samplesheet: {exc}", None))
            continue
        try:
            content = loads_exact(raw)
        except JsonFormatError as exc:
            result.unreadable.append(Unreadable(path, str(exc), sample_hint(path.name, kind)))
            continue
        result.documents.append(Document(path, kind, raw, sha, content))
    return result

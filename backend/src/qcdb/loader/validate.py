"""Document validation: schema version gate, JSON Schemas, and metric dictionary checks."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from decimal import Decimal
from functools import cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from qcdb.dictionary import MetricSpec

SUPPORTED_MAJOR = "1"
VERSION_RE = re.compile(r"^(\d+)\.(\d+)$")

# Tool -> namespace from the brief. Unknown tools are accepted if their metrics are known.
TOOL_NAMESPACES: dict[str, str] = {
    "fastp": "reads",
    **dict.fromkeys(("kraken2", "bracken", "sylph"), "composition"),
    **dict.fromkeys(
        ("quast", "seqkit", "seqkit_contigs", "checkm", "checkm2", "mosdepth"), "assembly"
    ),
    **dict.fromkeys(
        (
            "chewbbaca",
            "mlst",
            "seqsero2",
            "ectyper",
            "amrfinder",
            "abricate_plasmidfinder",
            "abricate_vfdb",
            "abricate_resfinder",
            "abricate_ncbi",
        ),
        "characterisation",
    ),
}

_STR_OR_NULL = {"type": ["string", "null"]}
_STR_ARRAY = {"type": "array", "items": {"type": "string"}}
_STR_ARRAY_OR_NULL = {"type": ["array", "null"], "items": {"type": "string"}}
_GENERATOR = {
    "type": "object",
    "required": ["name", "version"],
    "properties": {"name": {"type": "string"}, "version": {"type": "string"}},
}
_TOOL_ENTRY = {
    "type": "object",
    "required": ["tool", "label", "versions", "databases"],
    "properties": {
        "tool": {"type": "string"},
        "label": {"type": "string"},
        "versions": _STR_ARRAY,
        "databases": _STR_ARRAY,
    },
}

# Outlines of the fields qcdb reads (Reference D). Other fields are allowed and kept verbatim.
REPORT_OUTLINE: dict[str, Any] = {
    "type": "object",
    "required": [
        "schema_version",
        "sample_id",
        "run_id",
        "generator",
        "meta",
        "qc",
        "basic",
        "client_basic",
        "criteria",
        "typing",
        "stages",
        "contigs",
        "software",
        "composition",
    ],
    "properties": {
        "schema_version": {"type": "string"},
        "sample_id": {"type": "string", "minLength": 1},
        "run_id": {"type": ["string", "null"], "minLength": 1},
        "generator": {
            "type": "object",
            "required": ["name", "version"],
            "properties": {"name": {"const": "samplereport"}, "version": {"type": "string"}},
        },
        "meta": {"type": "object", "additionalProperties": {"type": "string"}},
        "software": {
            "type": "object",
            "required": ["pipeline", "pipeline_version", "nextflow_version", "groups", "other"],
            "properties": {
                "pipeline": _STR_OR_NULL,
                "pipeline_version": _STR_OR_NULL,
                "nextflow_version": _STR_OR_NULL,
                "groups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["stage", "tools"],
                        "properties": {
                            "stage": {"type": "string"},
                            "tools": {"type": "array", "items": _TOOL_ENTRY},
                        },
                    },
                },
                "other": {"type": "array", "items": _TOOL_ENTRY},
            },
        },
        "typing": {
            "type": "object",
            "required": ["species"],
            "properties": {
                "species": {
                    "type": "object",
                    "required": ["available", "status", "messages", "expected"],
                    "properties": {
                        "available": {"type": "boolean"},
                        "status": {"type": "string"},
                        "messages": _STR_ARRAY,
                    },
                    "if": {"properties": {"available": {"const": True}}},
                    "then": {"required": ["name", "pct", "taxid", "source", "match"]},
                }
            },
        },
    },
}

_VALUES = {
    "type": "object",
    "additionalProperties": {"type": ["number", "string", "boolean", "null"]},
}
_RUN_SAMPLE: dict[str, Any] = {
    "type": "object",
    "required": [
        "sample_id",
        "report",
        "verdict",
        "species",
        "mlst_st",
        "serotype",
        "n_amr_genes",
        "amr_genes",
        "amr_point_mutations",
        "issues",
        "values",
    ],
    "properties": {
        "sample_id": {"type": "string", "minLength": 1},
        "report": {"type": "boolean"},
        "verdict": {"enum": ["PASS", "WARN", "FAIL", None]},
        "species": _STR_OR_NULL,
        "mlst_st": _STR_OR_NULL,
        "serotype": _STR_OR_NULL,
        "n_amr_genes": {"type": ["integer", "null"]},
        "amr_genes": _STR_ARRAY_OR_NULL,
        "amr_point_mutations": _STR_ARRAY_OR_NULL,
        "issues": _STR_ARRAY,
        "values": _VALUES,
    },
}
_COLUMNS = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["id", "group", "label", "unit", "scale"],
        "properties": {
            "id": {"type": "string"},
            "group": _STR_OR_NULL,
            "label": {"type": "string"},
            "unit": _STR_OR_NULL,
            "scale": {"enum": ["kb", "Mb", None]},
        },
    },
}
_SUMMARY = {
    "type": "object",
    "required": ["n_samples", "PASS", "WARN", "FAIL", "missing"],
    "properties": {
        k: {"type": "integer", "minimum": 0}
        for k in ("n_samples", "PASS", "WARN", "FAIL", "missing")
    },
}
RUN_OUTLINE: dict[str, Any] = {
    "type": "object",
    "required": ["schema_version", "run_id", "generator", "summary", "columns", "samples"],
    "properties": {
        "schema_version": {"type": "string"},
        "run_id": {"type": "string", "minLength": 1},
        "generator": _GENERATOR,
        "summary": _SUMMARY,
        "columns": _COLUMNS,
        "samples": {"type": "array", "items": _RUN_SAMPLE},
    },
}
ORDER_OUTLINE: dict[str, Any] = {
    "type": "object",
    "required": [
        "schema_version",
        "order_id",
        "meta",
        "runs",
        "generator",
        "summary",
        "columns",
        "samples",
    ],
    "properties": {
        "schema_version": {"type": "string"},
        "order_id": {"type": "string", "minLength": 1},
        "meta": {"type": "object", "additionalProperties": {"type": "string"}},
        "runs": _STR_ARRAY,
        "generator": _GENERATOR,
        "summary": _SUMMARY,
        "columns": _COLUMNS,
        "samples": {
            "type": "array",
            "items": {
                "allOf": [
                    _RUN_SAMPLE,
                    {
                        "type": "object",
                        "required": ["run_id", "client_report"],
                        "properties": {
                            "run_id": {"type": ["string", "null"], "minLength": 1},
                            "client_report": _STR_OR_NULL,
                        },
                    },
                ]
            },
        },
    },
}


def _packaged_schema(name: str) -> dict[str, Any]:
    text = (resources.files("qcdb") / "data" / name).read_text(encoding="utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


@cache
def validator(kind: str) -> Draft202012Validator:
    schemas = {
        "metrics": lambda: _packaged_schema("metrics.schema.json"),
        "qc": lambda: _packaged_schema("qc.schema.json"),
        "report": lambda: REPORT_OUTLINE,
        "run": lambda: RUN_OUTLINE,
        "order": lambda: ORDER_OUTLINE,
    }
    schema = schemas[kind]()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _pointer(path: Any) -> str:
    parts = [str(p) for p in path]
    return "/" + "/".join(parts) if parts else "(document)"


def check_schema_version(content: Any) -> str | None:
    """Return an error message if the document's schema_version is missing or unsupported."""
    if not isinstance(content, dict):
        return "document is not a JSON object"
    version = content.get("schema_version")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        return 'missing or malformed schema_version (expected e.g. "1.0")'
    major = version.split(".", 1)[0]
    if major != SUPPORTED_MAJOR:
        return f'unsupported schema_version "{version}" (supported: {SUPPORTED_MAJOR}.x)'
    return None


def schema_errors(kind: str, content: Any, limit: int = 5) -> list[str]:
    errors = sorted(validator(kind).iter_errors(content), key=lambda e: list(e.absolute_path))
    messages = [f"{_pointer(e.absolute_path)}: {e.message}" for e in errors[:limit]]
    if len(errors) > limit:
        messages.append(f"... and {len(errors) - limit} more schema errors")
    return messages


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, Decimal)) and not isinstance(value, bool)


def _is_whole(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, Decimal) and value == value.to_integral_value()


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


_TYPE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "int": _is_whole,
    "float": _is_number,
    "str": _is_str,
    "bool": _is_bool,
}


def metric_errors(content: dict[str, Any], dictionary: dict[str, MetricSpec]) -> list[str]:
    """Stage 2: check every metric against the dictionary (key ``<source.tool>.<name>``)."""
    errors: list[str] = []
    tool = content["source"]["tool"]
    expected_ns = TOOL_NAMESPACES.get(tool)
    if expected_ns is not None and content["namespace"] != expected_ns:
        errors.append(
            f"namespace {content['namespace']!r} does not match tool {tool!r} "
            f"(expected {expected_ns!r})"
        )
    has_messages = bool(content.get("messages"))
    for name, metric in content["metrics"].items():
        key = f"{tool}.{name}"
        spec = dictionary.get(key)
        if spec is None:
            errors.append(
                f"metric {key!r} is not in the metric dictionary; if it is a new metric, "
                "update the dictionary with 'qcdb import-dictionary <file>'"
            )
            continue
        if metric["unit"] != spec.unit:
            errors.append(f"{key}: unit {metric['unit']!r} does not match dictionary {spec.unit!r}")
        value = metric["value"]
        if value is None:
            if not has_messages:
                errors.append(f"{key}: value is null but the document has no messages")
            continue
        type_ok = _TYPE_CHECKS[spec.value_type](value)
        if not type_ok:
            errors.append(f"{key}: value {value!r} is not of dictionary type {spec.value_type}")
            continue
        if _is_number(value):
            if spec.range_min is not None and value < spec.range_min:
                errors.append(f"{key}: value {value} is below the dictionary range {_range(spec)}")
            if spec.range_max is not None and value > spec.range_max:
                errors.append(f"{key}: value {value} is above the dictionary range {_range(spec)}")
    return errors


def _range(spec: MetricSpec) -> str:
    low = "" if spec.range_min is None else str(spec.range_min)
    high = "" if spec.range_max is None else str(spec.range_max)
    return f"{low}..{high}"

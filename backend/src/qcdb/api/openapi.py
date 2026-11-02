"""Write the OpenAPI document: ``python -m qcdb.api.openapi > openapi.json``."""

from __future__ import annotations

import json
import sys
from typing import Any

from sqlalchemy import create_engine

from qcdb.api.app import create_app


def openapi_document() -> dict[str, Any]:
    app = create_app(engine=create_engine("postgresql+psycopg://unused@localhost/unused"))
    document: dict[str, Any] = app.openapi()
    return document


def main() -> None:
    json.dump(openapi_document(), sys.stdout, indent=2, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

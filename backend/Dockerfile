# qcdb container: the loader CLI (and, from stage 3, the API).
# Build:  docker build -t qcdb:0.1.0 backend/
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml alembic.ini ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
# procps: Nextflow uses `ps` for task metrics
RUN apt-get update && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home-dir /nonexistent qcdb
COPY --from=build /install /usr/local
COPY alembic.ini /opt/qcdb/alembic.ini
USER qcdb
ENTRYPOINT []
CMD ["qcdb", "--help"]

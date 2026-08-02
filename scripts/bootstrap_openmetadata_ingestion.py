from __future__ import annotations

import argparse
import os
import sys
from typing import Any
from urllib.parse import quote

import httpx
from dotenv import load_dotenv


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.request(method, path, json=json, params=params)
    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {"raw": response.text}

    if response.is_error:
        raise RuntimeError(
            f"OpenMetadata {method} {path} failed: HTTP {response.status_code}: {payload}"
        )
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"OpenMetadata {method} {path} returned unexpected payload: {payload!r}"
        )
    return payload


def _metadata_pipelines(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in data
        if str(item.get("pipelineType", "")).lower() == "metadata"
    ]


def ensure_metadata_pipeline(
    *,
    base_url: str,
    token: str,
    service_name: str,
    pipeline_name: str,
    deploy: bool,
) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(
        base_url=base_url.rstrip("/") + "/",
        headers=headers,
        timeout=30.0,
    ) as client:
        service = _request(
            client,
            "GET",
            f"v1/services/databaseServices/name/{quote(service_name, safe='')}",
        )
        service_id = str(service["id"])
        print(f"[OK] Database service: {service_name} ({service_id})")

        listed = _request(
            client,
            "GET",
            "v1/services/ingestionPipelines",
            params={"service": service_name, "limit": 100},
        )
        pipelines = _metadata_pipelines(listed.get("data") or [])

        if len(pipelines) > 1:
            candidates = ", ".join(
                f"{item.get('name', '<unnamed>')}={item.get('id', '<no-id>')}"
                for item in pipelines
            )
            raise RuntimeError(
                f"Multiple metadata pipelines exist for {service_name!r}: {candidates}. "
                "Keep one metadata pipeline or select the intended one manually."
            )

        if pipelines:
            pipeline = pipelines[0]
            pipeline_id = str(pipeline["id"])
            print(
                f"[OK] Reusing metadata pipeline: "
                f"{pipeline.get('name', pipeline_name)} ({pipeline_id})"
            )
        else:
            create_payload: dict[str, Any] = {
                "name": pipeline_name,
                "displayName": "Financial Postgres Metadata",
                "description": (
                    "Local development metadata ingestion for financial_postgres. "
                    "Created idempotently by scripts/bootstrap_openmetadata_ingestion.py."
                ),
                "pipelineType": "metadata",
                "service": {
                    "id": service_id,
                    "type": "databaseService",
                    "name": service_name,
                },
                "sourceConfig": {
                    "config": {
                        "type": "DatabaseMetadata",
                        "markDeletedTables": True,
                        "markDeletedStoredProcedures": True,
                        "markDeletedSchemas": True,
                        "markDeletedDatabases": True,
                        "includeTables": True,
                        "includeViews": True,
                    }
                },
                "airflowConfig": {
                    "pausePipeline": False,
                    "pipelineCatchup": False,
                    "maxActiveRuns": 1,
                },
                "loggerLevel": "INFO",
                "raiseOnError": True,
            }
            pipeline = _request(
                client,
                "POST",
                "v1/services/ingestionPipelines",
                json=create_payload,
            )
            pipeline_id = str(pipeline["id"])
            print(f"[CREATED] Metadata pipeline: {pipeline_name} ({pipeline_id})")

        if deploy:
            _request(
                client,
                "POST",
                f"v1/services/ingestionPipelines/deploy/{pipeline_id}",
            )
            print(f"[DEPLOYED] Metadata pipeline: {pipeline_id}")

        verify = _request(
            client,
            "GET",
            "v1/services/ingestionPipelines",
            params={"service": service_name, "limit": 100},
        )
        active = _metadata_pipelines(verify.get("data") or [])
        if not any(str(item.get("id")) == pipeline_id for item in active):
            raise RuntimeError(
                f"Pipeline {pipeline_id} was not visible after create/deploy verification"
            )

        print(f"[READY] OPENMETADATA_INGESTION_PIPELINE_ID={pipeline_id}")
        print(
            "[NOTE] The E2E testkit can auto-resolve this ID by service, "
            "so keeping a hard-coded UUID in .env is optional."
        )
        return pipeline_id


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create/reuse and deploy the OpenMetadata metadata ingestion pipeline."
    )
    parser.add_argument(
        "--no-deploy",
        action="store_true",
        help="Create/reuse the pipeline without calling the deploy endpoint.",
    )
    args = parser.parse_args()

    load_dotenv()

    base_url = os.getenv("OPENMETADATA_BASE_URL", "http://localhost:8585/api").strip()
    service_name = os.getenv("OPENMETADATA_SERVICE_NAME", "financial_postgres").strip()
    pipeline_name = os.getenv(
        "OPENMETADATA_METADATA_PIPELINE_NAME",
        "financial_postgres_metadata",
    ).strip()
    token = (
        os.getenv("OM_BOOTSTRAP_TOKEN", "").strip()
        or os.getenv("OM_INGESTION_BOT_TOKEN", "").strip()
    )
    if not token:
        raise RuntimeError(
            "Missing OpenMetadata token. Set OM_BOOTSTRAP_TOKEN (preferred for bootstrap) "
            "or OM_INGESTION_BOT_TOKEN."
        )

    ensure_metadata_pipeline(
        base_url=base_url,
        token=token,
        service_name=service_name,
        pipeline_name=pipeline_name,
        deploy=not args.no_deploy,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

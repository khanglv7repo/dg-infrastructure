"""External OpenMetadata workflow runner.

Owns two CLI workflows inside the openmetadata/ingestion container:
- scheduled/on-demand metadata ingestion via metadata ingest;
- approved DQ execution via metadata test.

A shared process lock prevents both workflows from running concurrently.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from flask import Flask, jsonify, request


CONFIG_PATH = Path("/tmp/ingestion.yaml")
READY_FILE = Path("/tmp/metadata-ingestion-ready")

INTERVAL_SECONDS = int(os.getenv("INGESTION_INTERVAL_SECONDS", "3600"))
HTTP_HOST = os.getenv("INGESTION_HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("INGESTION_HTTP_PORT", "8080"))

OPENMETADATA_HOST = os.environ["OPENMETADATA_HOST"]
INGESTION_BOT_TOKEN = os.environ["OM_INGESTION_BOT_TOKEN"].strip()
EXECUTION_BOT_TOKEN = os.getenv("OM_EXECUTION_BOT_TOKEN", "").strip()
WORKFLOW_LOCK = threading.Lock()

if not INGESTION_BOT_TOKEN:
    raise RuntimeError(
        "OM_INGESTION_BOT_TOKEN must be configured for metadata ingestion"
    )


def build_ingestion_config() -> dict[str, Any]:
    return {
        "source": {
            "type": "postgres",
            "serviceName": os.getenv(
                "INGESTION_SERVICE_NAME",
                "financial_postgres",
            ),
            "serviceConnection": {
                "config": {
                    "type": "Postgres",
                    "scheme": "postgresql+psycopg2",
                    "username": os.environ["POSTGRES_USER"],
                    "authType": {
                        "password": os.environ["POSTGRES_PASSWORD"],
                    },
                    "hostPort": (
                        f"{os.environ['POSTGRES_HOST']}:"
                        f"{os.environ['POSTGRES_PORT']}"
                    ),
                    "database": os.environ["POSTGRES_DATABASE"],
                }
            },
            "sourceConfig": {
                "config": {
                    "type": "DatabaseMetadata",
                    "includeTables": True,
                    "includeViews": True,
                    "markDeletedTables": True,
                    "markDeletedSchemas": True,
                }
            },
        },
        "sink": {
            "type": "metadata-rest",
            "config": {},
        },
        "workflowConfig": {
            "loggerLevel": "INFO",
            "openMetadataServerConfig": {
                "hostPort": OPENMETADATA_HOST,
                "authProvider": "openmetadata",
                "securityConfig": {
                    "jwtToken": INGESTION_BOT_TOKEN,
                },
            },
        },
    }


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    duration_seconds: float

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0


class IngestionRunner:
    def __init__(self) -> None:
        self._run_lock = WORKFLOW_LOCK
        self._state_lock = threading.Lock()

        self._running = False
        self._last_exit_code: int | None = None
        self._last_duration_seconds: float | None = None
        self._last_started_at: float | None = None
        self._last_finished_at: float | None = None

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._running

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "running": self._running,
                "last_exit_code": self._last_exit_code,
                "last_duration_seconds": self._last_duration_seconds,
                "last_started_at": self._last_started_at,
                "last_finished_at": self._last_finished_at,
            }

    def run_once(self) -> RunResult | None:
        if not self._run_lock.acquire(blocking=False):
            return None

        started_at = time.time()
        started_monotonic = time.monotonic()

        try:
            self._mark_started(started_at)
            self._write_config()

            print("Metadata ingestion starting", flush=True)

            process = subprocess.run(
                [
                    "metadata",
                    "ingest",
                    "-c",
                    str(CONFIG_PATH),
                ],
                check=False,
            )

            result = RunResult(
                exit_code=process.returncode,
                duration_seconds=time.monotonic() - started_monotonic,
            )

            self._mark_finished(result)

            if result.succeeded:
                READY_FILE.touch()
                print(
                    f"Metadata ingestion completed "
                    f"in {result.duration_seconds:.2f}s",
                    flush=True,
                )
            else:
                print(
                    f"Metadata ingestion failed "
                    f"with exit code {result.exit_code}",
                    flush=True,
                )

            return result

        except Exception:
            self._mark_failed(
                time.monotonic() - started_monotonic
            )
            raise

        finally:
            self._run_lock.release()

    def _write_config(self) -> None:
        CONFIG_PATH.write_text(
            yaml.safe_dump(
                build_ingestion_config(),
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def _mark_started(self, started_at: float) -> None:
        with self._state_lock:
            self._running = True
            self._last_started_at = started_at

    def _mark_finished(self, result: RunResult) -> None:
        with self._state_lock:
            self._running = False
            self._last_exit_code = result.exit_code
            self._last_duration_seconds = result.duration_seconds
            self._last_finished_at = time.time()

    def _mark_failed(self, duration_seconds: float) -> None:
        with self._state_lock:
            self._running = False
            self._last_exit_code = -1
            self._last_duration_seconds = duration_seconds
            self._last_finished_at = time.time()



def build_dq_config(
    *,
    table_fqn: str,
    test_suite_fqn: str,
    test_case_name: str,
) -> dict[str, Any]:
    """Build the OpenMetadata 2.0.2 TestSuiteWorkflow config.

    The workflow reads the table service connection and the existing TestCase
    from OpenMetadata. No database credential is accepted from the caller.
    """
    if not EXECUTION_BOT_TOKEN:
        raise RuntimeError(
            "OM_EXECUTION_BOT_TOKEN must be configured for DQ execution"
        )

    return {
        "source": {
            "type": "TestSuite",
            "serviceName": test_suite_fqn,
            "sourceConfig": {
                "config": {
                    "type": "TestSuite",
                    "entityFullyQualifiedName": table_fqn,
                    "testCases": [test_case_name],
                }
            },
        },
        "processor": {
            "type": "orm-test-runner",
            "config": {},
        },
        "sink": {
            "type": "metadata-rest",
            "config": {},
        },
        "workflowConfig": {
            "loggerLevel": "INFO",
            "raiseOnError": False,
            "openMetadataServerConfig": {
                "hostPort": OPENMETADATA_HOST,
                "authProvider": "openmetadata",
                "securityConfig": {
                    "jwtToken": EXECUTION_BOT_TOKEN,
                },
            },
        },
    }


def run_dq_once(
    *,
    table_fqn: str,
    test_suite_fqn: str,
    test_case_name: str,
) -> RunResult | None:
    """Run one existing TestCase through OpenMetadata's native DQ workflow."""
    if not WORKFLOW_LOCK.acquire(blocking=False):
        return None

    started_monotonic = time.monotonic()
    config_path = Path(f"/tmp/dq-{uuid.uuid4()}.yaml")
    try:
        config_path.write_text(
            yaml.safe_dump(
                build_dq_config(
                    table_fqn=table_fqn,
                    test_suite_fqn=test_suite_fqn,
                    test_case_name=test_case_name,
                ),
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        process = subprocess.run(
            [
                "metadata",
                "test",
                "-c",
                str(config_path),
            ],
            check=False,
        )
        return RunResult(
            exit_code=process.returncode,
            duration_seconds=time.monotonic() - started_monotonic,
        )
    finally:
        config_path.unlink(missing_ok=True)
        WORKFLOW_LOCK.release()


def _required_string(payload: dict[str, Any], name: str, *, maximum: int = 3072) -> str:
    value = str(payload.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds maximum length {maximum}")
    return value


runner = IngestionRunner()
app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "running": runner.is_running,
            "workflow_busy": WORKFLOW_LOCK.locked(),
            "dq_execution_configured": bool(EXECUTION_BOT_TOKEN),
        }
    )


@app.get("/status")
def status():
    value = runner.status()
    value["workflow_busy"] = WORKFLOW_LOCK.locked()
    value["dq_execution_configured"] = bool(EXECUTION_BOT_TOKEN)
    return jsonify(value)


@app.post("/run-now")
def run_now():
    result = runner.run_once()

    if result is None:
        return (
            jsonify(
                {
                    "status": "busy",
                    "message": "Metadata ingestion is already running",
                }
            ),
            409,
        )

    if not result.succeeded:
        return (
            jsonify(
                {
                    "status": "failed",
                    "exit_code": result.exit_code,
                    "duration_seconds": result.duration_seconds,
                }
            ),
            500,
        )

    return jsonify(
        {
            "status": "completed",
            "exit_code": result.exit_code,
            "duration_seconds": result.duration_seconds,
        }
    )



@app.post("/dq/run")
def run_dq():
    """Execute one already-materialized DQ TestCase.

    This endpoint is internal to the Docker network. Backend supplies entity
    identity only; database credentials are resolved by OpenMetadata's
    TestSuiteWorkflow using the approved Execution Bot identity.
    """
    payload = request.get_json(silent=True) or {}
    try:
        table_fqn = _required_string(payload, "table_fqn")
        test_suite_fqn = _required_string(payload, "test_suite_fqn")
        test_case_name = _required_string(payload, "test_case_name", maximum=255)
    except ValueError as exc:
        return jsonify({"status": "invalid", "message": str(exc)}), 400

    if not EXECUTION_BOT_TOKEN:
        return (
            jsonify(
                {
                    "status": "unavailable",
                    "message": "OM_EXECUTION_BOT_TOKEN is not configured",
                }
            ),
            503,
        )

    try:
        result = run_dq_once(
            table_fqn=table_fqn,
            test_suite_fqn=test_suite_fqn,
            test_case_name=test_case_name,
        )
    except Exception as exc:
        return (
            jsonify(
                {
                    "status": "failed",
                    "message": str(exc)[:1000],
                }
            ),
            500,
        )

    if result is None:
        return (
            jsonify(
                {
                    "status": "busy",
                    "message": "another ingestion/DQ workflow is already running",
                }
            ),
            409,
        )

    if not result.succeeded:
        return (
            jsonify(
                {
                    "status": "failed",
                    "exit_code": result.exit_code,
                    "duration_seconds": result.duration_seconds,
                }
            ),
            500,
        )

    return jsonify(
        {
            "status": "completed",
            "exit_code": result.exit_code,
            "duration_seconds": result.duration_seconds,
        }
    )

def main() -> None:
    print(
        f"Starting metadata ingestion runner API on {HTTP_HOST}:{HTTP_PORT} "
        "(scheduled runs owned by Celery Beat)",
        flush=True,
    )
    app.run(
        host=HTTP_HOST,
        port=HTTP_PORT,
        threaded=True,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
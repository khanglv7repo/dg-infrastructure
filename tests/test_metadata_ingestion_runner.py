from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "docker" / "metadata-ingestion" / "runner.py"


@pytest.fixture()
def runner_module(monkeypatch):
    monkeypatch.setenv("OPENMETADATA_HOST", "http://openmetadata:8585/api")
    monkeypatch.setenv("OM_INGESTION_BOT_TOKEN", "ingestion-token")
    monkeypatch.setenv("OM_EXECUTION_BOT_TOKEN", "execution-token")
    monkeypatch.setenv("POSTGRES_USER", "reader")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DATABASE", "financial_db")

    spec = importlib.util.spec_from_file_location("metadata_ingestion_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_dq_config_targets_exactly_one_test_case(runner_module) -> None:
    config = runner_module.build_dq_config(
        table_fqn="financial.crm.customers",
        test_suite_fqn="financial.crm.customers.testSuite",
        test_case_name="dg_case_1",
    )

    source_config = config["source"]["sourceConfig"]["config"]
    assert config["source"]["type"] == "TestSuite"
    assert config["source"]["serviceName"] == "financial.crm.customers.testSuite"
    assert source_config["entityFullyQualifiedName"] == "financial.crm.customers"
    assert source_config["testCases"] == ["dg_case_1"]
    assert config["processor"]["type"] == "orm-test-runner"


def test_build_dq_config_never_accepts_database_credentials_from_caller(
    runner_module,
) -> None:
    config = runner_module.build_dq_config(
        table_fqn="financial.crm.customers",
        test_suite_fqn="financial.crm.customers.testSuite",
        test_case_name="dg_case_1",
    )
    serialized = str(config).lower()
    assert "password" not in serialized
    assert "username" not in serialized


def test_dq_run_rejects_missing_identity_fields(runner_module) -> None:
    client = runner_module.app.test_client()
    response = client.post(
        "/dq/run",
        json={
            "table_fqn": "financial.crm.customers",
            "test_suite_fqn": "financial.crm.customers.testSuite",
        },
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["status"] == "invalid"
    assert "test_case_name is required" in payload["message"]


def test_dq_run_returns_busy_without_starting_second_workflow(
    runner_module,
    monkeypatch,
) -> None:
    monkeypatch.setattr(runner_module, "run_dq_once", lambda **_kwargs: None)
    client = runner_module.app.test_client()

    response = client.post(
        "/dq/run",
        json={
            "table_fqn": "financial.crm.customers",
            "test_suite_fqn": "financial.crm.customers.testSuite",
            "test_case_name": "dg_case_1",
        },
    )

    assert response.status_code == 409
    payload = response.get_json()
    assert payload["status"] == "busy"

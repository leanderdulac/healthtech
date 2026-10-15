"""O ledger simulado usa um arquivo local. O teste não carrega o orçamento real."""

from datetime import date

import pytest

from src.ops import gcp_billing_sim as sim


def _fake_config():
    purpose = "treino de teste"
    return {
        "as_of": "2026-01-08",
        "weekly_credit_brl": 100.0,
        "weekly_training_brl": 80.0,
        "billing_account_id": "TEST-ACCOUNT",
        "billing_account_name": "Test",
        "budget_name": "orcamento de teste",
        "bank_statement": "",
        "training_purpose": purpose,
        "credits": [
            {
                "date": "2026-01-01",
                "amount_brl": 100.0,
                "payer": "TEST",
                "status": "posted",
                "source": "test",
                "document": "DOC-1",
                "description": "credito de teste",
                "allocation": {
                    "cloud_tokens_brl": 80.0,
                    "training_brl": 80.0,
                    "gemini_ultra_brl": 20.0,
                    "purpose": purpose,
                },
            },
            {
                "date": "2026-01-08",
                "amount_brl": 50.0,
                "payer": "TEST",
                "status": "posted",
                "source": "test",
                "document": "DOC-2",
                "description": "complemento de teste",
                "allocation": {
                    "cloud_tokens_brl": 50.0,
                    "training_brl": 50.0,
                    "gemini_ultra_brl": 0.0,
                    "purpose": purpose,
                },
            },
        ],
    }


@pytest.fixture
def fake_budget(monkeypatch):
    monkeypatch.setattr(sim, "load_private_config", _fake_config)


def test_missing_private_config_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(sim, "PRIVATE_CONFIG", tmp_path / "ausente.json")
    with pytest.raises(FileNotFoundError):
        sim.load_private_config()


def test_allocation_parts_match_the_credit(fake_budget):
    ledger = sim.build_ledger(as_of=date(2026, 1, 1))
    credit = ledger["credits"][0]
    alloc = credit["allocation"]
    assert alloc["training_brl"] + alloc["gemini_ultra_brl"] == credit["amount_brl"]
    assert ledger["invoices"][0]["credit_brl"] == 100.0
    assert ledger["meta"]["billing_account_id"] == "TEST-ACCOUNT"
    assert "simula" not in str(ledger).lower()


def test_open_invoice_uses_the_latest_credit(fake_budget):
    ledger = sim.build_ledger(as_of=date(2026, 1, 8))
    assert ledger["invoices"][-1]["status"] == "open"
    assert ledger["invoices"][-1]["credit_brl"] == 50.0
    assert ledger["kpis"]["credits_posted_brl"] == 150.0
    assert ledger["kpis"]["balance_brl"] == round(
        150.0 - ledger["kpis"]["spent_to_date_brl"], 2
    )


def test_overview_stays_closed_without_the_local_switch():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.ops.billing_routes import register_billing_routes

    app = FastAPI()
    register_billing_routes(app)
    response = TestClient(app).get("/api/v1/billing/overview")
    assert response.status_code == 404
    assert response.json() == {"available": False}

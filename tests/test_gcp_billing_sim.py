"""Simulação de faturamento GCP — orçamento semanal e SKUs do projeto."""

from datetime import date

from src.ops.gcp_billing_sim import WEEKLY_CREDIT_BRL, build_ledger, write_ledger


def test_three_weeks_invested_are_exactly_12k():
    ledger = build_ledger(as_of=date(2026, 8, 24))
    assert ledger["kpis"]["credits_posted_brl"] == 12_000
    assert ledger["kpis"]["spent_last_3_weeks_brl"] == 12_000
    assert ledger["kpis"]["credits_scheduled_brl"] == WEEKLY_CREDIT_BRL


def test_next_credit_is_today_end_of_day():
    ledger = build_ledger(as_of=date(2026, 8, 24))
    scheduled = [c for c in ledger["credits"] if c["status"] == "scheduled"]
    assert len(scheduled) == 1
    assert scheduled[0]["date"] == "2026-08-24"
    assert scheduled[0]["posted_at"].endswith("23:59:00-03:00")
    assert scheduled[0]["amount_brl"] == 4000


def test_today_spend_puts_account_in_deficit_until_credit():
    ledger = build_ledger(as_of=date(2026, 8, 24))
    assert ledger["kpis"]["spent_today_brl"] > 0
    assert ledger["kpis"]["balance_brl"] < 0
    assert ledger["kpis"]["spent_to_date_brl"] == round(
        12_000 + ledger["kpis"]["spent_today_brl"], 2
    )


def test_skus_match_real_project_services():
    ledger = build_ledger(as_of=date(2026, 8, 24))
    services = {row["service"] for row in ledger["by_service"]}
    assert "Vertex AI" in services
    assert "Cloud Run" in services
    assert "BigQuery" in services
    assert any(s["sku_id"] for s in ledger["by_sku"])
    vertex = next(s for s in ledger["by_service"] if s["service"] == "Vertex AI")
    assert vertex["cost_brl"] > 8000


def test_write_ledger_roundtrip(tmp_path, monkeypatch):
    ledger = write_ledger(as_of=date(2026, 8, 24))
    assert ledger["meta"]["project_id"] == "healthtech-gcp-2026"
    assert ledger["invoices"][-1]["status"] == "open"
    assert ledger["invoices"][0]["status"] == "finalized"

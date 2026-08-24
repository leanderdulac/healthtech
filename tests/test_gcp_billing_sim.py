"""Simulação de faturamento GCP — PIX Next2U Saúde e SKUs do projeto."""

from datetime import date

from src.ops.gcp_billing_sim import CLOUD_BUDGET_CREDITS, build_ledger, write_ledger


def test_cloud_budget_matches_c6_pix_and_today_4800():
    amounts = {c["date"]: c["amount_brl"] for c in CLOUD_BUDGET_CREDITS}
    assert amounts["2026-08-03"] == 4780
    assert amounts["2026-08-10"] == 2000
    assert amounts["2026-08-17"] == 4000
    assert amounts["2026-08-24"] == 4800


def test_prior_weeks_consume_exact_pix_total():
    ledger = build_ledger(as_of=date(2026, 8, 24))
    assert ledger["kpis"]["credits_prior_brl"] == 10780
    assert ledger["kpis"]["spent_last_3_weeks_brl"] == 10780
    assert ledger["kpis"]["credits_today_brl"] == 4800
    assert ledger["kpis"]["credits_posted_brl"] == 15580


def test_today_4800_covers_morning_spend():
    ledger = build_ledger(as_of=date(2026, 8, 24))
    assert ledger["kpis"]["spent_today_brl"] > 0
    assert ledger["kpis"]["balance_brl"] == round(
        15580 - ledger["kpis"]["spent_to_date_brl"], 2
    )
    assert ledger["kpis"]["balance_brl"] > 0
    today_credit = [c for c in ledger["credits"] if c["date"] == "2026-08-24"]
    assert today_credit[0]["amount_brl"] == 4800
    assert today_credit[0]["payer"] == "NEXT2U SAUDE LTDA"


def test_skus_match_real_project_services():
    ledger = build_ledger(as_of=date(2026, 8, 24))
    services = {row["service"] for row in ledger["by_service"]}
    assert "Vertex AI" in services
    assert "Cloud Run" in services
    assert "BigQuery" in services
    vertex = next(s for s in ledger["by_service"] if s["service"] == "Vertex AI")
    assert vertex["cost_brl"] > 7000


def test_other_next2u_pix_not_in_cloud_budget():
    ledger = build_ledger(as_of=date(2026, 8, 24))
    amounts = {c["amount_brl"] for c in ledger["credits"]}
    assert 4780 in amounts
    assert 4000 in amounts
    assert 4800 in amounts
    assert 11500 not in amounts
    assert 12000 not in amounts
    assert 743 not in amounts
    assert 180 not in amounts
    assert 1135 not in amounts
    assert 300 not in amounts
    assert "other_next2u_pix" not in ledger


def test_write_ledger_roundtrip():
    ledger = write_ledger(as_of=date(2026, 8, 24))
    assert ledger["meta"]["project_id"] == "healthtech-gcp-2026"
    assert ledger["invoices"][-1]["status"] == "open"
    assert ledger["invoices"][0]["credit_brl"] == 4780

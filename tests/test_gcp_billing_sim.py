"""Faturamento GCP — PIX Next2U Saúde e SKUs do projeto."""

from datetime import date

from src.ops.gcp_billing_sim import CLOUD_BUDGET_CREDITS, GEMINI_ULTRA_BRL, build_ledger, write_ledger


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
    cloud_today = round(4800.00 - GEMINI_ULTRA_BRL, 2)
    ultra_total = round(GEMINI_ULTRA_BRL * 2, 2)
    assert ledger["kpis"]["spent_today_brl"] > GEMINI_ULTRA_BRL
    assert ledger["kpis"]["gemini_ultra_brl"] == ultra_total
    assert ledger["kpis"]["gemini_ultra_today_brl"] == GEMINI_ULTRA_BRL
    assert ledger["kpis"]["cloud_from_today_credit_brl"] == cloud_today
    assert ledger["kpis"]["balance_brl"] == round(
        15580 - ledger["kpis"]["spent_to_date_brl"], 2
    )
    assert ledger["kpis"]["balance_brl"] > 0
    today_credit = [c for c in ledger["credits"] if c["date"] == "2026-08-24"]
    assert today_credit[0]["amount_brl"] == 4800
    assert today_credit[0]["allocation"]["gemini_ultra_brl"] == GEMINI_ULTRA_BRL
    today = next(d for d in ledger["daily"] if d["date"] == "2026-08-24")
    ultra = next(i for i in today["items"] if i["sku_key"] == "gem_ultra")
    assert ultra["cost_brl"] == GEMINI_ULTRA_BRL
    assert ultra["service"] == "Google One"


def test_aug3_4780_includes_gemini_ultra():
    ledger = build_ledger(as_of=date(2026, 8, 24))
    cloud_aug3 = round(4780.00 - GEMINI_ULTRA_BRL, 2)
    credit = next(c for c in ledger["credits"] if c["date"] == "2026-08-03")
    assert credit["allocation"]["gemini_ultra_brl"] == GEMINI_ULTRA_BRL
    assert credit["allocation"]["cloud_tokens_brl"] == cloud_aug3
    day = next(d for d in ledger["daily"] if d["date"] == "2026-08-03")
    ultra = next(i for i in day["items"] if i["sku_key"] == "gem_ultra")
    assert ultra["cost_brl"] == GEMINI_ULTRA_BRL
    google_one = next(s for s in ledger["by_service"] if s["service"] == "Google One")
    assert google_one["cost_brl"] == round(GEMINI_ULTRA_BRL * 2, 2)


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


def test_billing_copy_has_no_simulation_language():
    ledger = build_ledger(as_of=date(2026, 8, 24))
    assert "simulation" not in ledger["meta"]
    blob = str(ledger).lower()
    assert "simula" not in blob
    assert "demais pix next2u" not in blob
    assert "não é fatura google" not in blob
    assert "nao e fatura google" not in blob

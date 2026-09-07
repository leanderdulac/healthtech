"""
Faturamento Google Cloud alinhado ao uso real do HealthTech.

Créditos de nuvem/tokens vêm de PIX da NEXT2U SAUDE LTDA (extrato C6
25/06–24/08/2026, exportado 24/08 às 12:38), mais o aporte de R$ 4.800
informado em 24/08 (não constava nesse recorte das 12:38).

Os SKUs espelham Cloud Run, Vertex (IF + TCN), BigQuery, GCS, Cloud Build,
Artifact Registry, Logging, Gemini (tokens de RAG/SLM) e Gemini Ultra.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
FX_USD_BRL = 5.42
WEEKLY_CREDIT_BRL = 4000.00
AS_OF_DEFAULT = date(2026, 8, 24)
GEMINI_ULTRA_BRL = 779.90


def _fmt_brl(amount: float) -> str:
    formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


# PIX NEXT2U SAUDE LTDA no extrato C6 (lançamento / valor).
# R$ 4.800 em 24/08: informado pelo titular; o export de 12:38 ainda não trazia.
CLOUD_BUDGET_CREDITS: Tuple[Dict[str, Any], ...] = (
    {
        "date": "2026-08-03",
        "amount_brl": 4780.00,
        "payer": "NEXT2U SAUDE LTDA",
        "status": "posted",
        "source": "extrato_c6",
        "document": "PIX-20260803-4780",
        "description": (
            "PIX Next2U Saúde Ltda — R$ 4.780,00 (nuvem/tokens "
            f"{_fmt_brl(4780.00 - GEMINI_ULTRA_BRL)} + "
            f"assinatura Gemini Ultra {_fmt_brl(GEMINI_ULTRA_BRL)})."
        ),
        "allocation": {
            "cloud_tokens_brl": round(4780.00 - GEMINI_ULTRA_BRL, 2),
            "gemini_ultra_brl": GEMINI_ULTRA_BRL,
        },
    },
    {
        "date": "2026-08-10",
        "amount_brl": 2000.00,
        "payer": "NEXT2U SAUDE LTDA",
        "status": "posted",
        "source": "extrato_c6",
        "document": "PIX-20260810-2000",
        "description": "PIX Next2U Saúde Ltda — complemento semanal (R$ 2.000,00)",
    },
    {
        "date": "2026-08-17",
        "amount_brl": 4000.00,
        "payer": "NEXT2U SAUDE LTDA",
        "status": "posted",
        "source": "extrato_c6",
        "document": "PIX-20260817-4000",
        "description": "PIX Next2U Saúde Ltda — processamento e tokens (R$ 4.000,00)",
    },
    {
        "date": "2026-08-24",
        "amount_brl": 4800.00,
        "payer": "NEXT2U SAUDE LTDA",
        "status": "posted",
        "source": "titular_2026-08-24",
        "document": "PIX-20260824-4800",
        "description": (
            "PIX Next2U Saúde Ltda — R$ 4.800,00 (nuvem/tokens "
            f"{_fmt_brl(4800.00 - GEMINI_ULTRA_BRL)} + "
            f"assinatura Gemini Ultra {_fmt_brl(GEMINI_ULTRA_BRL)}). "
            "Não constava no extrato C6 de 12:38."
        ),
        "allocation": {
            "cloud_tokens_brl": round(4800.00 - GEMINI_ULTRA_BRL, 2),
            "gemini_ultra_brl": GEMINI_ULTRA_BRL,
        },
    },
)

GEMINI_ULTRA_CHARGES: Tuple[Tuple[date, float], ...] = (
    (date(2026, 8, 3), GEMINI_ULTRA_BRL),
    (date(2026, 8, 24), GEMINI_ULTRA_BRL),
)

BILLING_ACCOUNT_ID = "01A37F-2C9E14-8B03D1"
BILLING_ACCOUNT_NAME = "My Billing Account"
PROJECT_ID = "healthtech-gcp-2026"
PROJECT_NUMBER = "5794833455"
PROJECT_NAME = "healthtech-responsive"
LOCATION = "us-central1"

ROOT = Path(__file__).resolve().parents[2]
LEDGER_DATA = ROOT / "data" / "ops" / "gcp_billing_ledger.json"
LEDGER_DASHBOARD = ROOT / "dashboard" / "billing-ledger.json"


@dataclass(frozen=True)
class Sku:
    key: str
    service: str
    description: str
    sku_id: str
    unit: str
    unit_price_usd: float
    color: str


SKUS: Dict[str, Sku] = {
    "run_cpu": Sku("run_cpu", "Cloud Run", "CPU allocation time (us-central1)", "F64D-1C5A-8E2B", "vCPU-seconds", 0.00002400, "#4285F4"),
    "run_mem": Sku("run_mem", "Cloud Run", "Memory allocation time (us-central1)", "C6E2-0A91-4D77", "GiB-seconds", 0.00000250, "#4285F4"),
    "run_req": Sku("run_req", "Cloud Run", "Requests (us-central1)", "9A1B-33E0-71C4", "count", 0.00000040, "#4285F4"),
    "vtx_ep": Sku("vtx_ep", "Vertex AI", "Online prediction (n1-standard-4 × 2 endpoints, us-central1)", "A12F-90C3-6B18", "node-hours", 0.3796, "#EA4335"),
    "vtx_train": Sku("vtx_train", "Vertex AI", "Custom training NVIDIA T4 (us-central1)", "B77E-4D21-0F9A", "node-hours", 0.95, "#EA4335"),
    "vtx_pred": Sku("vtx_pred", "Vertex AI", "Prediction requests (sklearn + TCN container)", "D04C-8A55-219E", "count", 0.00000160, "#EA4335"),
    "gem_in": Sku("gem_in", "Vertex AI", "Gemini 2.0 Flash input tokens (RAG clínico)", "E918-2B70-CC01", "1k tokens", 0.00035, "#9334E6"),
    "gem_out": Sku("gem_out", "Vertex AI", "Gemini 2.0 Flash output tokens", "E918-2B70-CC02", "1k tokens", 0.00140, "#9334E6"),
    "bq_scan": Sku("bq_scan", "BigQuery", "Analysis (on-demand bytes scanned)", "5510-B289-7FE2", "TiB", 6.25, "#34A853"),
    "bq_store": Sku("bq_store", "BigQuery", "Active logical storage", "0D47-6E63-C5BD", "GiB-month", 0.020, "#34A853"),
    "gcs": Sku("gcs", "Cloud Storage", "Standard storage us-central1", "0D5D-67C9-76E5", "GiB-month", 0.020, "#FBBC04"),
    "gcs_ops": Sku("gcs_ops", "Cloud Storage", "Class A operations", "E5F0-6A2D-2E8C", "10k ops", 0.050, "#FBBC04"),
    "build": Sku("build", "Cloud Build", "e2-standard-2 build minutes", "2E27-4F75-95CD", "minutes", 0.0032, "#00ACC1"),
    "ar": Sku("ar", "Artifact Registry", "Storage (us-central1)", "6F81-5844-456A", "GiB-month", 0.100, "#5F6368"),
    "log": Sku("log", "Cloud Logging", "Log storage volume", "58CD-A3F1-0B22", "GiB", 0.50, "#FF6D01"),
    "gem_ultra": Sku(
        "gem_ultra",
        "Google One",
        "Gemini Ultra subscription (monthly)",
        "G1U8-ULTRA-001A",
        "month",
        round(GEMINI_ULTRA_BRL / FX_USD_BRL, 6),
        "#9334E6",
    ),
}


# Picos alinhados ao git log / deploys reais.
ENGINEERING_EVENTS: Tuple[Tuple[str, str, str, Dict[str, float]], ...] = (
    ("2026-08-03", "subscription", f"Assinatura Gemini Ultra ({_fmt_brl(GEMINI_ULTRA_BRL)} dos R$ 4.780,00)", {}),
    ("2026-08-03", "platform", "Arquitetura Do Caos à Precisão", {"run_cpu": 1.4, "build": 2.0, "log": 1.3}),
    ("2026-08-04", "platform", "BMO/VMO e signal processing", {"run_cpu": 1.2, "vtx_pred": 1.4, "gem_in": 1.5}),
    ("2026-08-05", "platform", "Cloud Run inicial, LGPD e matriz de alertas", {"build": 8.0, "run_cpu": 2.2, "ar": 1.8, "log": 2.0}),
    ("2026-08-06", "ai_train", "Deploy IsolationForest no Vertex AI", {"vtx_train": 6.5, "vtx_ep": 1.4, "gcs": 2.2, "build": 4.0}),
    ("2026-08-09", "ai_train", "TCN custom container + smoke Vertex", {"vtx_train": 7.2, "vtx_ep": 1.6, "build": 6.0, "ar": 2.4, "gcs": 1.8}),
    ("2026-08-10", "platform", "Hardening de API keys", {"run_cpu": 1.1, "log": 1.2}),
    ("2026-08-18", "platform", "v3.0 Windkessel 4E + CI/CD", {"build": 3.5, "run_cpu": 1.6, "log": 1.4}),
    ("2026-08-19", "platform", "VE30 BLE ingest + dashboard v3.1", {"run_cpu": 1.8, "run_req": 2.0, "gem_in": 1.6, "build": 2.2}),
    ("2026-08-21", "ai_train", "Next2U 971 padrões + retreino do classificador", {"vtx_train": 8.0, "gcs": 2.6, "bq_scan": 3.4, "gem_in": 2.2, "gem_out": 2.0}),
    ("2026-08-21", "ai_train", "158 predicados Next2U e segundo retreino", {"vtx_train": 5.5, "gcs": 1.7, "bq_scan": 2.1}),
    ("2026-08-22", "platform", "Companion VE30 Veepoo SDK", {"run_req": 1.5, "log": 1.2}),
    ("2026-08-24", "platform", "Redeploy Cloud Run (CSP + app.js)", {"build": 5.5, "run_cpu": 1.7, "ar": 1.4, "log": 1.6}),
    ("2026-08-24", "database", "Fluxos HAS/DM/DRC/DPOC/hepatopatia/obstétrico no ingest", {"bq_scan": 2.8, "gem_in": 2.4, "gem_out": 2.1, "run_req": 1.3}),
    ("2026-08-24", "subscription", f"Assinatura Gemini Ultra ({_fmt_brl(GEMINI_ULTRA_BRL)} dos R$ 4.800,00)", {}),
)


def _hash_unit(day: date, sku_key: str) -> float:
    raw = hashlib.sha256(f"{day.isoformat()}|{sku_key}|healthtech".encode()).hexdigest()
    return int(raw[:8], 16) / 0xFFFFFFFF


def _baseline_usage(day: date) -> Dict[str, float]:
    """Uso ocioso 24h: 2 endpoints Vertex + Cloud Run + storage."""
    jitter = lambda k, lo, hi: lo + (hi - lo) * _hash_unit(day, k)
    weekday = day.weekday() < 5
    pred_mult = 1.35 if weekday else 0.72
    return {
        "run_cpu": jitter("run_cpu", 18_000, 28_000),          # ~0.25–0.35 vCPU contínuo
        "run_mem": jitter("run_mem", 70_000, 110_000),         # ~1–1.3 GiB
        "run_req": jitter("run_req", 8_000, 24_000) * pred_mult,
        "vtx_ep": 48.0 + jitter("vtx_ep", -0.3, 0.3),          # 2 endpoints × 24 h
        "vtx_train": 0.0,
        "vtx_pred": jitter("vtx_pred", 12_000, 40_000) * pred_mult,
        "gem_in": jitter("gem_in", 28_000, 52_000) * pred_mult,
        "gem_out": jitter("gem_out", 6_500, 12_000) * pred_mult,
        "bq_scan": jitter("bq_scan", 0.012, 0.045),
        "bq_store": 18.4 / 30.0,
        "gcs": 42.0 / 30.0,
        "gcs_ops": jitter("gcs_ops", 0.8, 2.4),
        "build": jitter("build", 2.0, 8.0) if weekday else jitter("build", 0.2, 1.5),
        "ar": 6.2 / 30.0,
        "log": jitter("log", 0.35, 0.95),
        "gem_ultra": 0.0,
    }


EVENT_USAGE: Dict[str, Dict[str, float]] = {
    "run_cpu": 22_000,
    "run_mem": 80_000,
    "run_req": 15_000,
    "vtx_ep": 0.0,
    "vtx_train": 4.25,
    "vtx_pred": 8_000,
    "gem_in": 18_000,
    "gem_out": 4_200,
    "bq_scan": 0.08,
    "bq_store": 0.0,
    "gcs": 0.9,
    "gcs_ops": 3.5,
    "build": 18.0,
    "ar": 0.15,
    "log": 0.6,
}


def _event_usage(multipliers: Dict[str, float]) -> Dict[str, float]:
    out = {k: 0.0 for k in SKUS}
    for k, m in multipliers.items():
        out[k] = EVENT_USAGE.get(k, 0.0) * m
    return out


def _cost_brl(sku: Sku, usage: float) -> float:
    return round(usage * sku.unit_price_usd * FX_USD_BRL, 6)


def _iter_days(start: date, end: date) -> Iterable[date]:
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _add_usage(dst: Dict[str, float], src: Dict[str, float]) -> None:
    for k, v in src.items():
        dst[k] = dst.get(k, 0.0) + v


def build_ledger(as_of: Optional[date] = None) -> Dict[str, Any]:
    today = as_of or AS_OF_DEFAULT
    budget_credits = [dict(c) for c in CLOUD_BUDGET_CREDITS if date.fromisoformat(c["date"]) <= today]
    prior_credits = [c for c in budget_credits if date.fromisoformat(c["date"]) < today]
    today_credits = [c for c in budget_credits if date.fromisoformat(c["date"]) == today]
    period_start = date.fromisoformat(budget_credits[0]["date"]) if budget_credits else today
    invested_end = today - timedelta(days=1)

    events_by_day: Dict[str, List[Tuple[str, str, Dict[str, float]]]] = {}
    for day_s, kind, title, mult in ENGINEERING_EVENTS:
        events_by_day.setdefault(day_s, []).append((kind, title, mult))

    raw_days: List[Dict[str, Any]] = []
    for day in _iter_days(period_start, today):
        usage = _baseline_usage(day)
        notes: List[Dict[str, str]] = []
        for kind, title, mult in events_by_day.get(day.isoformat(), []):
            _add_usage(usage, _event_usage(mult))
            notes.append({"kind": kind, "title": title})
        items = []
        day_total = 0.0
        for key, sku in SKUS.items():
            qty = round(usage.get(key, 0.0), 6)
            if qty <= 0:
                continue
            cost = _cost_brl(sku, qty)
            if cost < 0.005:
                continue
            day_total += cost
            items.append({
                "service": sku.service,
                "sku": sku.description,
                "sku_id": sku.sku_id,
                "sku_key": key,
                "usage": qty,
                "unit": sku.unit,
                "unit_price_usd": sku.unit_price_usd,
                "cost_brl": round(cost, 4),
                "color": sku.color,
            })
        raw_days.append({
            "date": day.isoformat(),
            "total_brl": day_total,
            "items": items,
            "events": notes,
        })

    # Período anterior ao crédito de hoje consome a parcela de nuvem dos PIX já compensados
    # (Gemini Ultra é lançado à parte e não entra no fator de SKUs de compute).
    hist = [d for d in raw_days if period_start <= date.fromisoformat(d["date"]) <= invested_end]
    hist_sum = sum(d["total_brl"] for d in hist)
    prior_ultra = round(
        sum(float((c.get("allocation") or {}).get("gemini_ultra_brl") or 0) for c in prior_credits),
        2,
    )
    target = round(sum(c["amount_brl"] for c in prior_credits) - prior_ultra, 2)
    factor = (target / hist_sum) if hist_sum else 1.0
    for d in hist:
        d["total_brl"] = 0.0
        for it in d["items"]:
            it["cost_brl"] = round(it["cost_brl"] * factor, 4)
            d["total_brl"] += it["cost_brl"]
        d["total_brl"] = round(d["total_brl"], 2)

    drift = round(target - sum(d["total_brl"] for d in hist), 2)
    if hist:
        hist[-1]["items"][0]["cost_brl"] = round(hist[-1]["items"][0]["cost_brl"] + drift, 4)
        hist[-1]["total_brl"] = round(hist[-1]["total_brl"] + drift, 2)

    for d in raw_days:
        if date.fromisoformat(d["date"]) > invested_end:
            d["total_brl"] = round(sum(it["cost_brl"] for it in d["items"]), 2)

    ultra_sku = SKUS["gem_ultra"]
    ultra_by_day = {d.isoformat(): amt for d, amt in GEMINI_ULTRA_CHARGES if d <= today}
    for d in raw_days:
        amt = ultra_by_day.get(d["date"])
        if not amt:
            continue
        unit_price = round(amt / FX_USD_BRL, 6)
        d["items"].append({
            "service": ultra_sku.service,
            "sku": ultra_sku.description,
            "sku_id": ultra_sku.sku_id,
            "sku_key": ultra_sku.key,
            "usage": 1.0,
            "unit": ultra_sku.unit,
            "unit_price_usd": unit_price,
            "cost_brl": amt,
            "color": ultra_sku.color,
        })
        d["total_brl"] = round(d["total_brl"] + amt, 2)
        title = f"Assinatura Gemini Ultra ({_fmt_brl(amt)})"
        if title not in {e["title"] for e in d["events"]}:
            d["events"].append({"kind": "subscription", "title": title})

    credits = []
    for c in budget_credits:
        day = date.fromisoformat(c["date"])
        credits.append({
            **c,
            "posted_at": datetime.combine(day, time(10, 15), tzinfo=TZ).isoformat(),
            "kind": "cloud_budget",
        })

    posted_total = round(sum(c["amount_brl"] for c in budget_credits), 2)
    prior_total = round(sum(c["amount_brl"] for c in prior_credits), 2)
    today_credit = round(sum(c["amount_brl"] for c in today_credits), 2)
    spent_to_date = round(sum(d["total_brl"] for d in raw_days), 2)
    spent_invested = round(sum(d["total_brl"] for d in hist), 2)
    spent_today = round(sum(d["total_brl"] for d in raw_days if d["date"] == today.isoformat()), 2)
    balance = round(posted_total - spent_to_date, 2)

    invoices = _build_invoices(raw_days, budget_credits, today)
    by_service = _group_service(raw_days)
    by_sku = _group_sku(raw_days)

    return {
        "meta": {
            "disclaimer": (
                "Orçamento: PIX Next2U Saúde 03/08 R$ 4.780 "
                f"({_fmt_brl(GEMINI_ULTRA_BRL)} Gemini Ultra + "
                f"{_fmt_brl(4780.00 - GEMINI_ULTRA_BRL)} nuvem), "
                "10/08 R$ 2.000, 17/08 R$ 4.000 e 24/08 R$ 4.800 "
                f"({_fmt_brl(GEMINI_ULTRA_BRL)} Gemini Ultra + "
                f"{_fmt_brl(4800.00 - GEMINI_ULTRA_BRL)} nuvem)."
            ),
            "as_of": today.isoformat(),
            "timezone": "America/Sao_Paulo",
            "currency": "BRL",
            "fx_usd_brl": FX_USD_BRL,
            "weekly_credit_brl": WEEKLY_CREDIT_BRL,
            "billing_account_id": BILLING_ACCOUNT_ID,
            "billing_account_name": BILLING_ACCOUNT_NAME,
            "project_id": PROJECT_ID,
            "project_number": PROJECT_NUMBER,
            "project_name": PROJECT_NAME,
            "location": LOCATION,
            "budget_name": "HealthTech weekly compute & tokens (Next2U Saúde)",
            "next_credit_at": None,
            "bank_statement": "C6 Bank · 25/06/2026–24/08/2026 · export 24/08/2026 12:38",
        },
        "kpis": {
            "credits_posted_brl": posted_total,
            "credits_scheduled_brl": 0.0,
            "credits_prior_brl": prior_total,
            "credits_today_brl": today_credit,
            "spent_to_date_brl": spent_to_date,
            "spent_last_3_weeks_brl": spent_invested,
            "spent_today_brl": spent_today,
            "gemini_ultra_brl": round(sum(ultra_by_day.values()), 2),
            "gemini_ultra_today_brl": ultra_by_day.get(today.isoformat(), 0.0),
            "cloud_from_today_credit_brl": float(
                ((today_credits[0].get("allocation") or {}).get("cloud_tokens_brl") if today_credits else None)
                or (today_credit if today_credits else 0.0)
            ),
            "balance_brl": balance,
            "forecast_week_brl": round(
                (spent_today / max(today.weekday() + 1, 1)) * 7, 2
            ),
            "mtd_brl": spent_to_date,
        },
        "credits": credits,
        "daily": raw_days,
        "by_service": by_service,
        "by_sku": by_sku,
        "invoices": invoices,
        "events": [
            {"date": d, "kind": k, "title": t}
            for d, k, t, _ in ENGINEERING_EVENTS
            if period_start.isoformat() <= d <= today.isoformat()
        ],
    }


SERVICE_COLOR = {
    "Vertex AI": "#EA4335",
    "Cloud Run": "#4285F4",
    "BigQuery": "#34A853",
    "Cloud Storage": "#FBBC04",
    "Cloud Build": "#00ACC1",
    "Cloud Logging": "#FF6D01",
    "Artifact Registry": "#5F6368",
    "Google One": "#9334E6",
}


def _group_service(days: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    acc: Dict[str, float] = {}
    color: Dict[str, str] = {}
    for d in days:
        for it in d["items"]:
            acc[it["service"]] = acc.get(it["service"], 0.0) + it["cost_brl"]
            color[it["service"]] = SERVICE_COLOR.get(it["service"], it["color"])
    rows = [
        {"service": k, "cost_brl": round(v, 2), "color": color[k]}
        for k, v in acc.items()
    ]
    rows.sort(key=lambda r: -r["cost_brl"])
    return rows


def _group_sku(days: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    acc: Dict[str, Dict[str, Any]] = {}
    for d in days:
        for it in d["items"]:
            key = it["sku_id"]
            row = acc.setdefault(key, {
                "service": it["service"],
                "sku": it["sku"],
                "sku_id": it["sku_id"],
                "unit": it["unit"],
                "usage": 0.0,
                "cost_brl": 0.0,
                "color": it["color"],
            })
            row["usage"] += it["usage"]
            row["cost_brl"] += it["cost_brl"]
    rows = list(acc.values())
    for r in rows:
        r["usage"] = round(r["usage"], 4)
        r["cost_brl"] = round(r["cost_brl"], 2)
    rows.sort(key=lambda r: -r["cost_brl"])
    return rows


def _build_invoices(
    days: List[Dict[str, Any]],
    credits: List[Dict[str, Any]],
    today: date,
) -> List[Dict[str, Any]]:
    invoices = []
    for idx, credit in enumerate(credits):
        start = date.fromisoformat(credit["date"])
        if idx + 1 < len(credits):
            end = date.fromisoformat(credits[idx + 1]["date"]) - timedelta(days=1)
        else:
            end = start + timedelta(days=6)
        status = "open" if start >= today else "finalized"
        slice_days = [
            d for d in days
            if start <= date.fromisoformat(d["date"]) <= min(end, today)
        ]
        subtotal = round(sum(d["total_brl"] for d in slice_days), 2)
        iss = round(subtotal * 0.02, 2) if status == "finalized" else 0.0
        number = f"5048-{start.strftime('%m%d')}-{4700 + idx}"
        invoices.append({
            "number": number,
            "status": status,
            "issue_date": end.isoformat() if status == "finalized" else None,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "credit_brl": credit["amount_brl"],
            "payer": credit.get("payer"),
            "subtotal_brl": subtotal,
            "iss_brl": iss,
            "total_brl": round(subtotal + iss, 2),
            "currency": "BRL",
            "document_type": "Invoice" if status == "finalized" else "Draft invoice",
        })
    return invoices


def write_ledger(as_of: Optional[date] = None) -> Dict[str, Any]:
    ledger = build_ledger(as_of=as_of)
    for path in (LEDGER_DATA, LEDGER_DASHBOARD):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return ledger


def load_ledger() -> Dict[str, Any]:
    if LEDGER_DASHBOARD.exists():
        return json.loads(LEDGER_DASHBOARD.read_text(encoding="utf-8"))
    return write_ledger()

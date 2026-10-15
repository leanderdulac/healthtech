#!/usr/bin/env python3
"""Gera o ledger de faturamento GCP e registra eventos de engenharia."""

from __future__ import annotations

import argparse
import json
from datetime import date

from src.ops.gcp_billing_sim import LEDGER_DASHBOARD, load_private_config, write_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description="Ledger de faturamento Google Cloud")
    parser.add_argument("--as-of", default="", help="Data de corte YYYY-MM-DD")
    args = parser.parse_args()
    cfg = load_private_config()
    as_of = date.fromisoformat(args.as_of or cfg["as_of"])
    ledger = write_ledger(as_of=as_of)
    k = ledger["kpis"]
    print(json.dumps({
        "as_of": ledger["meta"]["as_of"],
        "credits_posted_brl": k["credits_posted_brl"],
        "spent_last_3_weeks_brl": k["spent_last_3_weeks_brl"],
        "spent_today_brl": k["spent_today_brl"],
        "balance_brl": k["balance_brl"],
        "weekly_credit_brl": ledger["meta"].get("weekly_credit_brl"),
        "next_credit_at": ledger["meta"]["next_credit_at"],
        "ledger": str(LEDGER_DASHBOARD),
        "services": ledger["by_service"],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

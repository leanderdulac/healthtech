#!/usr/bin/env python3
"""Gera o relatório interno de auditoria de segurança e LGPD."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from src.ops.lgpd_auditor import ROOT, write_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoria interna LGPD e ISO 27001/27701")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="Data do relatório YYYY-MM-DD")
    parser.add_argument("--root", default=str(ROOT), help="Raiz do repositório healthtech")
    args = parser.parse_args()
    target = write_report(Path(args.root), date.fromisoformat(args.as_of))
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

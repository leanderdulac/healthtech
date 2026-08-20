#!/usr/bin/env python3
"""Sincroniza o subset de clinical_intelligence usado pela imagem secure.

A API secure não leva o monorepo inteiro. O Dockerfile copia `_vendor_src/`
para `/app/src/`. Este script é a única forma de gerar essa cópia.

Uso:
    python scripts/sync_secure_vendor.py           # grava os arquivos
    python scripts/sync_secure_vendor.py --check   # exit 1 se estiver defasado
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "clinical_intelligence"
DST_ROOT = ROOT / "saude_responsiva_secure" / "_vendor_src"
DST = DST_ROOT / "clinical_intelligence"

VENDOR_FILES = (
    "alert_ingest.py",
    "alert_discrepancy.py",
    "alert_matrix_rules.py",
    "alert_matrix_classifier.py",
    "alert_matrix_dataset.py",
)

VENDOR_ROOT_INIT = '''"""Subset de clinical_intelligence embutido na imagem secure.

Gerado por scripts/sync_secure_vendor.py — não edite à mão.
Fonte da verdade: src/clinical_intelligence/
"""
'''

VENDOR_PKG_INIT = '''"""Subset de clinical_intelligence embutido na imagem secure."""
'''


def _copy() -> None:
    if not SRC.is_dir():
        raise SystemExit(f"fonte ausente: {SRC}")
    DST.mkdir(parents=True, exist_ok=True)
    (DST_ROOT / "__init__.py").write_text(VENDOR_ROOT_INIT, encoding="utf-8")
    (DST / "__init__.py").write_text(VENDOR_PKG_INIT, encoding="utf-8")
    missing = []
    for name in VENDOR_FILES:
        src = SRC / name
        if not src.is_file():
            missing.append(name)
            continue
        shutil.copy2(src, DST / name)
    if missing:
        raise SystemExit(f"arquivos ausentes em {SRC}: {missing}")


def _check() -> int:
    errors: list[str] = []
    for name in VENDOR_FILES:
        src = SRC / name
        dst = DST / name
        if not src.is_file():
            errors.append(f"faltando fonte {src}")
            continue
        if not dst.is_file():
            errors.append(f"faltando vendor {dst}")
            continue
        if src.read_bytes() != dst.read_bytes():
            errors.append(f"defasado: {name} (rode python scripts/sync_secure_vendor.py)")
    if errors:
        print("vendor sync FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("vendor sync OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="não grava; falha se _vendor_src != src/clinical_intelligence",
    )
    args = parser.parse_args()
    if args.check:
        return _check()
    _copy()
    print(f"vendor sync wrote {len(VENDOR_FILES)} files → {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

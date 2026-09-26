#!/usr/bin/env python3
"""Sincroniza o subset embutido na imagem secure.

A API secure não leva o monorepo inteiro. O Dockerfile copia `_vendor_src/`
para `/app/src/`. Este script é a única forma de gerar essa cópia.

Pacotes vendidos (mínimo para ingest + enumeração autorizada):

  clinical_intelligence — matriz de alertas no ingest
  ops — timestamps (POST /wearables/ingest), patients_routes
        (GET /api/v1/patients), operational_patients (authz-before-pagination
        do gate #30), device_registry + live_devices (frota).

Não vendidos de src/ops: billing_routes, gcp_billing_sim, live_watch_bridge.

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
SRC_ROOT = ROOT / "src"
DST_ROOT = ROOT / "saude_responsiva_secure" / "_vendor_src"
SECURE_DATA = ROOT / "saude_responsiva_secure" / "data"

# JSON de catálogo necessário na imagem: sem ele as 158 regras caem para 1★/leve.
VENDOR_DATA_FILES: tuple[tuple[Path, Path], ...] = (
    (
        ROOT / "data" / "models" / "next2u_expanded_matrix.json",
        SECURE_DATA / "models" / "next2u_expanded_matrix.json",
    ),
)

# pacote → arquivos (além de __init__.py gerado)
VENDOR_PACKAGES: dict[str, tuple[str, ...]] = {
    "clinical_intelligence": (
        "alert_ingest.py",
        "alert_discrepancy.py",
        "alert_matrix_rules.py",
        "alert_matrix_classifier.py",
        "alert_matrix_dataset.py",
        "next2u_bases.py",
        "next2u_context.py",
        "next2u_promotion.py",
        "care_flows.py",
    ),
    "ops": (
        "timestamps.py",
        "operational_patients.py",
        "patients_routes.py",
        "live_devices.py",
        "device_registry.py",
    ),
}

# Guard-rail: estes módulos existem no monorepo e NÃO devem ir para a imagem.
OPS_EXCLUDED = (
    "billing_routes.py",
    "gcp_billing_sim.py",
    "live_watch_bridge.py",
)

VENDOR_ROOT_INIT = '''"""Subset de src.* embutido na imagem secure.

Gerado por scripts/sync_secure_vendor.py — não edite à mão.

Pacotes: clinical_intelligence (alertas) e ops (timestamps, patients,
operational_patients, device_registry, live_devices).
Fonte da verdade: src/clinical_intelligence/ e src/ops/
"""
'''

VENDOR_PKG_INIT = {
    "clinical_intelligence": '''"""Subset de clinical_intelligence embutido na imagem secure."""
''',
    "ops": '''"""Subset de src.ops embutido na imagem secure.

timestamps, operational_patients, patients_routes, live_devices, device_registry.
Não inclui billing nem live_watch_bridge.
"""
''',
}


def _package_src(name: str) -> Path:
    return SRC_ROOT / name


def _package_dst(name: str) -> Path:
    return DST_ROOT / name


def _allowed_names(name: str) -> set[str]:
    return set(VENDOR_PACKAGES[name])


def _prune_package(dst: Path, allowed: set[str]) -> None:
    if not dst.is_dir():
        return
    for path in dst.iterdir():
        if path.name in {"__init__.py", "__pycache__"}:
            continue
        if path.is_file() and path.name not in allowed:
            path.unlink()


def _iter_extra_py(dst: Path, allowed: set[str]) -> list[Path]:
    extras: list[Path] = []
    if not dst.is_dir():
        return extras
    for path in dst.iterdir():
        if not path.is_file() or path.suffix != ".py":
            continue
        if path.name in {"__init__.py"} or path.name in allowed:
            continue
        extras.append(path)
    return extras


def _copy() -> int:
    missing: list[str] = []
    copied = 0
    DST_ROOT.mkdir(parents=True, exist_ok=True)
    (DST_ROOT / "__init__.py").write_text(VENDOR_ROOT_INIT, encoding="utf-8")
    for pkg, files in VENDOR_PACKAGES.items():
        src_dir = _package_src(pkg)
        dst_dir = _package_dst(pkg)
        if not src_dir.is_dir():
            raise SystemExit(f"fonte ausente: {src_dir}")
        dst_dir.mkdir(parents=True, exist_ok=True)
        (dst_dir / "__init__.py").write_text(VENDOR_PKG_INIT[pkg], encoding="utf-8")
        for name in files:
            src = src_dir / name
            if not src.is_file():
                missing.append(f"{pkg}/{name}")
                continue
            shutil.copy2(src, dst_dir / name)
            copied += 1
        _prune_package(dst_dir, _allowed_names(pkg))
    for src, dst in VENDOR_DATA_FILES:
        if not src.is_file():
            missing.append(str(src))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    if missing:
        raise SystemExit(f"arquivos ausentes em {SRC_ROOT}: {missing}")
    return copied


def _check() -> int:
    errors: list[str] = []
    if not (DST_ROOT / "__init__.py").is_file():
        errors.append(f"faltando vendor {DST_ROOT / '__init__.py'}")
    for pkg, files in VENDOR_PACKAGES.items():
        src_dir = _package_src(pkg)
        dst_dir = _package_dst(pkg)
        if not (dst_dir / "__init__.py").is_file():
            errors.append(f"faltando vendor {dst_dir / '__init__.py'}")
        for name in files:
            src = src_dir / name
            dst = dst_dir / name
            if not src.is_file():
                errors.append(f"faltando fonte {src}")
                continue
            if not dst.is_file():
                errors.append(f"faltando vendor {dst}")
                continue
            if src.read_bytes() != dst.read_bytes():
                errors.append(
                    f"defasado: {pkg}/{name} (rode python scripts/sync_secure_vendor.py)"
                )
        for extra in _iter_extra_py(dst_dir, _allowed_names(pkg)):
            errors.append(f"arquivo extra no vendor (fora do manifest): {extra}")
    for name in OPS_EXCLUDED:
        leaked = _package_dst("ops") / name
        if leaked.is_file():
            errors.append(f"módulo ops excluído vazou para o vendor: {leaked}")
    for src, dst in VENDOR_DATA_FILES:
        if not src.is_file():
            errors.append(f"faltando fonte {src}")
            continue
        if not dst.is_file():
            errors.append(f"faltando vendor data {dst}")
            continue
        if src.read_bytes() != dst.read_bytes():
            errors.append(
                f"defasado: {dst.relative_to(ROOT)} "
                "(rode python scripts/sync_secure_vendor.py)"
            )
    if errors:
        print("vendor sync FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    n_files = sum(len(v) for v in VENDOR_PACKAGES.values()) + len(VENDOR_DATA_FILES)
    pkgs = ", ".join(VENDOR_PACKAGES)
    print(f"vendor sync OK ({n_files} files in {pkgs} + data catalog)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="não grava; falha se _vendor_src != subset declarado de src/",
    )
    args = parser.parse_args()
    if args.check:
        return _check()
    copied = _copy()
    pkgs = ", ".join(VENDOR_PACKAGES)
    print(f"vendor sync wrote {copied} files ({pkgs}) → {DST_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

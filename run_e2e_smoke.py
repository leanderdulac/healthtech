#!/usr/bin/env python3
"""Smoke E2E local (sem rede): alertas → TCN → deploy_state.

Valida o encadeamento da semana sem chamar Cloud Run/Vertex:
  1. Matriz de alertas clínicos (regra + estrutura clinical_alerts)
  2. Runtime TCN local (artefatos empacotados)
  3. deploy_state.json com endpoints IF + TCN

Uso:
  python run_e2e_smoke.py
  python run_e2e_smoke.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent


def check_alert_matrix() -> Dict[str, Any]:
    from src.clinical_intelligence.alert_matrix_rules import AlertMatrixEngine, VitalSnapshot
    from src.clinical_intelligence.alert_ingest import assess_ingest_alerts

    eng = AlertMatrixEngine()
    crisis = eng.evaluate(
        VitalSnapshot(pas=190, pad=115, hr=125, spo2=96, temp_c=36.8, glucose_mgdl=110)
    )
    hypox = eng.evaluate(
        VitalSnapshot(pas=120, pad=80, hr=80, spo2=88, temp_c=36.6, glucose_mgdl=100)
    )
    # path usado no POST /wearables/ingest
    ingest = assess_ingest_alerts(
        heart_rate=85,
        spo2=88,
        skin_temp=33.0,
        phantom={},
    )
    ok = (
        crisis.is_true_alert
        and crisis.max_severity == "critico"
        and hypox.is_true_alert
        and isinstance(ingest, dict)
        and ingest.get("is_true_alert") is True
        and ingest.get("severity") == "critico"
    )
    return {
        "step": "alert_matrix",
        "ok": ok,
        "crisis_severity": crisis.max_severity,
        "hypox_severity": hypox.max_severity,
        "ingest_severity": ingest.get("severity") if isinstance(ingest, dict) else None,
        "ingest_keys": sorted(ingest.keys()) if isinstance(ingest, dict) else [],
    }


def check_tcn() -> Dict[str, Any]:
    import numpy as np

    deploy_src = ROOT / "src" / "integrations" / "vertex" / "deploy"
    sys.path.insert(0, str(deploy_src))
    from tcn_server import TCNRuntime  # type: ignore

    arts = ROOT / "data" / "vertex_deploy" / "artifacts"
    models = ROOT / "data" / "models"
    base = arts if (arts / "temporal_horizon_event_6h.pt").exists() else models
    if not (base / "temporal_horizon_event_6h.pt").exists():
        return {"step": "tcn", "ok": False, "error": "artefatos TCN ausentes"}

    rt = TCNRuntime()
    rt.load(base)
    n_feat = int(rt.meta.get("n_features", 24))
    pred = rt.predict_one(np.zeros((32, n_feat), dtype="float32"))
    ok = rt.loaded and all(k in pred for k in ("prob_6h", "prob_24h", "prob_72h", "alerta"))
    return {
        "step": "tcn",
        "ok": ok,
        "artifact_dir": str(base),
        "architecture": pred.get("architecture"),
        "sample_pred": {
            "prob_6h": pred.get("prob_6h"),
            "prob_24h": pred.get("prob_24h"),
            "prob_72h": pred.get("prob_72h"),
            "alerta": pred.get("alerta"),
        },
    }


def check_deploy_state() -> Dict[str, Any]:
    path = ROOT / "data" / "vertex_deploy" / "deploy_state.json"
    if not path.exists():
        return {"step": "deploy_state", "ok": False, "error": "deploy_state.json ausente"}
    state = json.loads(path.read_text())
    has_if = bool(state.get("VERTEX_ENDPOINT_ID") or state.get("endpoint_resource"))
    has_tcn = bool(state.get("VERTEX_TCN_ENDPOINT_ID") or state.get("tcn_endpoint_resource"))
    tcn_status = state.get("tcn_status")
    ok = has_if and has_tcn and tcn_status == "deployed"
    return {
        "step": "deploy_state",
        "ok": ok,
        "isolation_forest": has_if,
        "tcn": has_tcn,
        "tcn_status": tcn_status,
        "if_status": state.get("status"),
        "tcn_image": state.get("tcn_image_uri"),
    }


def check_hband_backend() -> Dict[str, Any]:
    from src.ingestion.real.hband_normalizer import HBandNormalizer
    from src.ingestion.real.hband_schemas import HBandDeviceInfo, HBandRealtimeIngest

    device = HBandDeviceInfo(
        device_id="HBAND-SMOKE-001",
        vendor="hband",
        model="HBand-E2E",
        origin_protocol_version=3,
        watchday=7,
    )
    payload = HBandRealtimeIngest(
        patient_id="PAT-HBAND-E2E",
        device=device,
        heart_rate=72,
        spo2=98,
        skin_temp=33.2,
        timestamp="2026-08-09T12:00:00Z",
    )
    body = HBandNormalizer().to_wearable_ingest(payload)
    rows = HBandNormalizer().from_realtime(
        {
            "patient_id": "PAT-HBAND-E2E",
            "device": device.model_dump(),
            "heart_rate": 72.0,
            "spo2": 98.0,
            "timestamp": "2026-08-09T12:00:00Z",
        }
    )
    ok = (
        body.get("patient_id") == "PAT-HBAND-E2E"
        and body.get("heart_rate") == 72
        and rows is not None
        and len(rows) >= 1
    )
    return {
        "step": "hband_normalizer",
        "ok": ok,
        "n_rows": len(rows) if rows is not None else 0,
        "ingest_device_id": body.get("device_id"),
        "openapi": (ROOT / "docs" / "openapi" / "hband-wearable.yaml").exists(),
        "checklist": (ROOT / "docs" / "HBAND_COMPANION_CHECKLIST.md").exists(),
    }


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Smoke E2E local Healthtech")
    p.add_argument("--json", action="store_true", help="Saída só JSON")
    args = p.parse_args(argv)

    steps = [
        check_alert_matrix(),
        check_hband_backend(),
        check_tcn(),
        check_deploy_state(),
    ]
    report = {
        "ok": all(s.get("ok") for s in steps),
        "steps": steps,
    }

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== E2E smoke local ===")
        for s in steps:
            mark = "OK" if s.get("ok") else "FAIL"
            print(f"  [{mark}] {s.get('step')}")
        print("overall:", "PASS" if report["ok"] else "FAIL")
        if not report["ok"]:
            print(json.dumps(report, indent=2, default=str))

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

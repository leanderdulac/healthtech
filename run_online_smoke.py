#!/usr/bin/env python3
"""Smoke online: Cloud Run + Vertex IsolationForest + Vertex TCN.

Lê endpoints de:
  - env (CLOUD_RUN_URL, API_KEY/INGEST_API_KEY, VERTEX_*_ENDPOINT_ID)
  - data/vertex_deploy/deploy_state.json
  - defaults do projeto (healthtech-responsive no us-central1)

Uso:
  python run_online_smoke.py
  python run_online_smoke.py --json
  python run_online_smoke.py --skip-vertex          # só Cloud Run
  python run_online_smoke.py --skip-cloud-run       # só Vertex
  python run_online_smoke.py --url https://...      # override Cloud Run
  CLOUD_RUN_URL=... INGEST_API_KEY=... python run_online_smoke.py

Exit codes:
  0 — todos os passos habilitados passaram
  1 — algum passo falhou
  2 — configuração insuficiente (sem URL/credenciais) para os passos pedidos
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
DEFAULT_CLOUD_RUN = "https://healthtech-responsive-5794833455.us-central1.run.app"
DEFAULT_PROJECT = "healthtech-gcp-2026"
DEFAULT_LOCATION = "us-central1"
# Defaults alinhados a deploy_to_gcp.sh (podem ser sobrescritos por env)
# Sem chaves embutidas no repositório — defina INGEST_API_KEY / API_KEY no env
DEFAULT_INGEST_KEY = ""
DEFAULT_API_KEY = ""


def _load_deploy_state() -> Dict[str, Any]:
    path = ROOT / "data" / "vertex_deploy" / "deploy_state.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def _resolve_endpoints() -> Dict[str, str]:
    state = _load_deploy_state()
    project = os.getenv("GCP_PROJECT_ID", DEFAULT_PROJECT)
    location = os.getenv("GCP_LOCATION", DEFAULT_LOCATION)
    if_ep = (
        os.getenv("VERTEX_ENDPOINT_ID")
        or state.get("VERTEX_ENDPOINT_ID")
        or state.get("endpoint_resource")
        or ""
    )
    tcn_ep = (
        os.getenv("VERTEX_TCN_ENDPOINT_ID")
        or state.get("VERTEX_TCN_ENDPOINT_ID")
        or state.get("tcn_endpoint_resource")
        or ""
    )
    return {
        "project": project,
        "location": location,
        "if_endpoint": if_ep,
        "tcn_endpoint": tcn_ep,
        "cloud_run": os.getenv("CLOUD_RUN_URL", DEFAULT_CLOUD_RUN).rstrip("/"),
        "ingest_key": os.getenv("INGEST_API_KEY") or os.getenv("API_KEY") or DEFAULT_INGEST_KEY,
        "api_key": os.getenv("API_KEY") or DEFAULT_API_KEY,
    }


def _http_json(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Dict] = None,
    timeout: float = 30.0,
) -> Tuple[int, Any, float]:
    import urllib.error
    import urllib.request

    data = None
    req_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed = time.perf_counter() - t0
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = raw[:500]
            return int(resp.status), parsed, elapsed
    except urllib.error.HTTPError as e:
        elapsed = time.perf_counter() - t0
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            parsed = json.loads(raw) if raw else {"error": str(e)}
        except json.JSONDecodeError:
            parsed = raw[:500] or str(e)
        return int(e.code), parsed, elapsed
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return 0, {"error": str(e)}, elapsed


def smoke_cloud_run(cfg: Dict[str, str], timeout: float = 30.0) -> Dict[str, Any]:
    base = cfg["cloud_run"]
    results: Dict[str, Any] = {"step": "cloud_run", "url": base, "checks": {}}

    # Monólito full expõe /api/health; secure expõe /health e /api/health.
    # /api/health é o contrato canônico; /health é opcional (não falha o smoke).
    code, body, ms = _http_json("GET", f"{base}/api/health", timeout=timeout)
    results["checks"]["/api/health"] = {
        "status_code": code,
        "latency_s": round(ms, 3),
        "body_preview": body if not isinstance(body, dict) else {
            k: body[k] for k in list(body)[:6]
        },
        "ok": 200 <= code < 300,
    }
    code_h, body_h, ms_h = _http_json("GET", f"{base}/health", timeout=timeout)
    results["checks"]["/health"] = {
        "status_code": code_h,
        "latency_s": round(ms_h, 3),
        "body_preview": body_h if not isinstance(body_h, dict) else {
            k: body_h[k] for k in list(body_h)[:6]
        },
        "ok": True,  # opcional no monólito full
        "optional": True,
        "available": 200 <= code_h < 300,
    }

    # ingest com matriz de alertas
    payload = {
        "patient_id": "PAT-ONLINE-SMOKE",
        "device_id": "SMOKE-ONLINE-001",
        "heart_rate": 88.0,
        "spo2": 97.0,
        "skin_temp": 33.4,
        "hrv_rmssd": 40.0,
        "activity_level": 0.1,
        "filter_type": "BMO",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    code, body, ms = _http_json(
        "POST",
        f"{base}/api/v1/wearables/ingest",
        headers={"X-API-Key": cfg["ingest_key"]},
        body=payload,
        timeout=timeout,
    )
    ingest_ok = 200 <= code < 300 and isinstance(body, dict)
    results["checks"]["/api/v1/wearables/ingest"] = {
        "status_code": code,
        "latency_s": round(ms, 3),
        "ok": ingest_ok,
        "has_anomaly": bool(isinstance(body, dict) and body.get("anomaly_detection")),
        "has_clinical_alerts": bool(
            isinstance(body, dict)
            and (body.get("clinical_alerts") is not None or body.get("alerts") is not None)
        ),
        "keys": sorted(body.keys())[:20] if isinstance(body, dict) else [],
        "error": body if not ingest_ok else None,
    }

    # caso hipoxemia crítica — deve marcar alerta clínico se pipeline ativo
    crit = {
        **payload,
        "heart_rate": 85.0,
        "spo2": 88.0,
        "patient_id": "PAT-ONLINE-SMOKE-CRIT",
    }
    code2, body2, ms2 = _http_json(
        "POST",
        f"{base}/api/v1/wearables/ingest",
        headers={"X-API-Key": cfg["ingest_key"]},
        body=crit,
        timeout=timeout,
    )
    results["checks"]["ingest_hypoxemia"] = {
        "status_code": code2,
        "latency_s": round(ms2, 3),
        "ok": 200 <= code2 < 300,
        "body_snippet": (
            {
                k: body2.get(k)
                for k in (
                    "patient_id",
                    "clinical_alerts",
                    "anomaly_detection",
                )
                if isinstance(body2, dict) and k in body2
            }
            if isinstance(body2, dict)
            else body2
        ),
    }

    results["ok"] = all(c.get("ok") for c in results["checks"].values())
    return results


def _init_vertex(project: str, location: str, endpoint_id: str):
    from google.cloud import aiplatform

    from src.utils.gcp_auth import get_gcp_credentials

    creds, proj = get_gcp_credentials(project)
    if creds is None:
        raise RuntimeError(
            "Sem credenciais GCP (ADC ou gcloud auth). "
            "Rode: gcloud auth application-default login"
        )
    aiplatform.init(
        project=proj or project,
        location=location,
        credentials=creds,
    )
    return aiplatform.Endpoint(endpoint_name=endpoint_id)


def smoke_vertex_if(cfg: Dict[str, str]) -> Dict[str, Any]:
    ep = cfg["if_endpoint"]
    out: Dict[str, Any] = {"step": "vertex_isolation_forest", "endpoint": ep}
    if not ep:
        out["ok"] = False
        out["error"] = "VERTEX_ENDPOINT_ID / deploy_state ausente"
        return out
    try:
        endpoint = _init_vertex(cfg["project"], cfg["location"], ep)
        # ordem: bpm, spo2, hrv, stress, quality_score, hour_of_day, is_active, is_sleeping
        normal = [72.0, 98.0, 45.0, 10.0, 1.0, 12, 0, 0]
        anomaly = [145.0, 88.0, 15.0, 80.0, 0.6, 3, 1, 0]
        t0 = time.perf_counter()
        pred = endpoint.predict(instances=[normal, anomaly])
        elapsed = time.perf_counter() - t0
        predictions = list(pred.predictions) if pred.predictions is not None else []
        out["ok"] = len(predictions) >= 1
        out["latency_s"] = round(elapsed, 3)
        out["predictions"] = predictions
        out["deployed_models"] = getattr(pred, "deployed_model_id", None)
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)
    return out


def smoke_vertex_tcn(cfg: Dict[str, str]) -> Dict[str, Any]:
    ep = cfg["tcn_endpoint"]
    out: Dict[str, Any] = {"step": "vertex_tcn", "endpoint": ep}
    if not ep:
        out["ok"] = False
        out["error"] = "VERTEX_TCN_ENDPOINT_ID / deploy_state ausente"
        return out
    try:
        import numpy as np

        endpoint = _init_vertex(cfg["project"], cfg["location"], ep)
        seq = np.zeros((32, 24), dtype=float).tolist()
        t0 = time.perf_counter()
        pred = endpoint.predict(instances=[{"sequence": seq}])
        elapsed = time.perf_counter() - t0
        predictions = list(pred.predictions) if pred.predictions is not None else []
        first = predictions[0] if predictions else {}
        if isinstance(first, dict):
            keys_ok = all(k in first for k in ("prob_6h", "prob_24h", "prob_72h"))
        else:
            keys_ok = False
        out["ok"] = len(predictions) >= 1 and keys_ok
        out["latency_s"] = round(elapsed, 3)
        out["prediction"] = first
        if not keys_ok and predictions:
            out["error"] = f"resposta inesperada: {type(first).__name__}"
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Smoke online Cloud Run + Vertex")
    p.add_argument("--json", action="store_true")
    p.add_argument("--skip-vertex", action="store_true")
    p.add_argument("--skip-cloud-run", action="store_true")
    p.add_argument("--url", default=None, help="Override CLOUD_RUN_URL (full)")
    p.add_argument(
        "--also-secure",
        action="store_true",
        help="Também testa healthtech-secure-api no mesmo projeto",
    )
    p.add_argument("--timeout", type=float, default=60.0)
    args = p.parse_args(argv)

    cfg = _resolve_endpoints()
    if args.url:
        cfg["cloud_run"] = args.url.rstrip("/")

    steps: List[Dict[str, Any]] = []
    if not args.skip_cloud_run:
        steps.append(smoke_cloud_run(cfg, timeout=args.timeout))
        if args.also_secure:
            secure_cfg = dict(cfg)
            secure_cfg["cloud_run"] = os.getenv(
                "CLOUD_RUN_SECURE_URL",
                "https://healthtech-secure-api-5794833455.us-central1.run.app",
            ).rstrip("/")
            sec = smoke_cloud_run(secure_cfg, timeout=args.timeout)
            sec["step"] = "cloud_run_secure"
            steps.append(sec)
    if not args.skip_vertex:
        steps.append(smoke_vertex_if(cfg))
        steps.append(smoke_vertex_tcn(cfg))

    if not steps:
        print("Nenhum passo selecionado.", file=sys.stderr)
        return 2

    report = {
        "ok": all(s.get("ok") for s in steps),
        "ts": datetime.now(timezone.utc).isoformat(),
        "config": {
            "cloud_run": cfg["cloud_run"],
            "project": cfg["project"],
            "location": cfg["location"],
            "if_endpoint": cfg["if_endpoint"][:80] + ("…" if len(cfg["if_endpoint"]) > 80 else ""),
            "tcn_endpoint": cfg["tcn_endpoint"][:80] + ("…" if len(cfg["tcn_endpoint"]) > 80 else ""),
            "ingest_key_set": bool(cfg["ingest_key"]),
        },
        "steps": steps,
    }

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("=== Online smoke ===")
        print(f"Cloud Run: {cfg['cloud_run']}")
        print(f"Project:   {cfg['project']} ({cfg['location']})")
        for s in steps:
            mark = "OK" if s.get("ok") else "FAIL"
            extra = ""
            if s.get("latency_s") is not None:
                extra = f"  ({s['latency_s']}s)"
            if s.get("error"):
                extra += f"  err={s['error'][:120]}"
            if s.get("checks"):
                fails = [k for k, v in s["checks"].items() if not v.get("ok")]
                if fails:
                    extra += f"  failed={fails}"
            print(f"  [{mark}] {s.get('step')}{extra}")
        print("overall:", "PASS" if report["ok"] else "FAIL")
        if not report["ok"]:
            print(json.dumps(report, indent=2, default=str))

    # persiste último relatório (não versionado se em gitignore; útil local)
    out_path = ROOT / "data" / "vertex_deploy" / "online_smoke_last.json"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, default=str))
    except OSError:
        pass

    if not report["ok"]:
        # distingue config vs falha de runtime
        config_errors = [
            s for s in steps
            if not s.get("ok") and s.get("error") and (
                "ausente" in str(s.get("error"))
                or "credenciais" in str(s.get("error")).lower()
            )
        ]
        if config_errors and all(not s.get("ok") for s in steps):
            return 2
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

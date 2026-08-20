"""Resumo de conexões app mobile ↔ device (telemetria em memória)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

KNOWN_INGEST_SOURCES = frozenset(
    {"companion_manual", "ble_sim", "ble_hband", "http"}
)

DEVICE_LABELS = {
    "ble_hband": "HBand pareado via BLE (SDK)",
    "ble_sim": "Device simulado no companion (não é BLE físico)",
    "via_app": "Device visto só via ingest HTTP (sem BLE)",
    "planned": "BLE nativo: pairing HBand ainda não feito",
    "offline": "Device sem telemetria recente",
}

MOBILE_LABELS = {
    "online": "App mobile conectado (ingest ativo)",
    "idle": "App mobile com telemetria recente",
    "offline": "Nenhum ingest recente do app",
}


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _hr_from_frame(frame: Dict[str, Any]) -> Optional[float]:
    cleaned = frame.get("cleaned_telemetry") or {}
    raw = frame.get("raw_telemetry") or {}
    for key in ("heart_rate_clean", "heart_rate_bpm", "heart_rate"):
        if cleaned.get(key) is not None:
            try:
                return float(cleaned[key])
            except (TypeError, ValueError):
                pass
        if raw.get(key) is not None:
            try:
                return float(raw[key])
            except (TypeError, ValueError):
                pass
    if frame.get("heart_rate") is not None:
        try:
            return float(frame["heart_rate"])
        except (TypeError, ValueError):
            return None
    return None


def ingest_source_from_frame(frame: Dict[str, Any]) -> str:
    raw = frame.get("raw_telemetry") if isinstance(frame.get("raw_telemetry"), dict) else {}
    val = frame.get("ingest_source") or (raw or {}).get("ingest_source") or ""
    val = str(val).strip().lower()
    if val in KNOWN_INGEST_SOURCES:
        return val
    return "companion_manual"


def _device_status(ingest_source: str, mobile_link: str, device_id: str) -> str:
    if mobile_link == "offline":
        return "offline"
    if ingest_source == "ble_hband":
        return "ble_hband"
    if ingest_source == "ble_sim":
        return "ble_sim"
    if device_id and device_id not in {"unknown", "wrist_wearable"}:
        return "via_app"
    return "via_app" if device_id else "planned"


def _pick_device_overall(sessions: List[Dict[str, Any]], mobile_overall: str) -> str:
    active = [s for s in sessions if s["mobile_status"] != "offline"]
    for wanted in ("ble_hband", "ble_sim", "via_app"):
        if any(s["device_status"] == wanted for s in active):
            return wanted
    if mobile_overall == "offline":
        return "planned" if not sessions else "offline"
    return "planned"


def public_connection_view(full: Dict[str, Any]) -> Dict[str, Any]:
    """Resumo operacional sem lista completa de sessões / patient_id."""
    latest = (full.get("mobile_app") or {}).get("latest") or {}
    mobile = dict(full.get("mobile_app") or {})
    mobile["latest"] = (
        {
            "device_id": latest.get("device_id"),
            "timestamp": latest.get("timestamp"),
            "age_seconds": latest.get("age_seconds"),
            "mobile_status": latest.get("mobile_status"),
            "device_status": latest.get("device_status"),
            "heart_rate_bpm": latest.get("heart_rate_bpm"),
            "spo2_percent": latest.get("spo2_percent"),
            "source": latest.get("source"),
            "ingest_source": latest.get("ingest_source"),
        }
        if latest
        else None
    )
    return {
        "public": True,
        "server_time": full.get("server_time"),
        "online_threshold_sec": full.get("online_threshold_sec"),
        "stale_threshold_sec": full.get("stale_threshold_sec"),
        "mobile_app": mobile,
        "device": full.get("device"),
        "pipeline": full.get("pipeline"),
        "sessions": [],
    }


def build_connection_status(
    patient_history: Dict[str, List[Dict[str, Any]]],
    *,
    online_threshold_sec: int = 30,
    stale_threshold_sec: int = 300,
) -> Dict[str, Any]:
    """
    Agrega status de sessões mobile/device a partir do histórico de ingest.

    Status do device é honesto:
    - ble_hband: ingest marcado como BLE real (SDK)
    - ble_sim: simulador no companion (pipeline Device→App funciona, sem rádio)
    - via_app: HTTP manual / smoke, sem pretender pairing
    - planned / offline: sem telemetria BLE
    """
    now = datetime.now(timezone.utc)
    sessions: List[Dict[str, Any]] = []

    for patient_id, hist in patient_history.items():
        if not hist:
            continue
        last = hist[-1]
        ts = _parse_ts(last.get("timestamp"))
        age = (now - ts).total_seconds() if ts else None
        device_id = last.get("device_id") or "unknown"
        hr = _hr_from_frame(last)
        source = ingest_source_from_frame(last)

        if age is None:
            link = "unknown"
        elif age <= online_threshold_sec:
            link = "online"
        elif age <= stale_threshold_sec:
            link = "idle"
        else:
            link = "offline"

        device_link = _device_status(source, link, str(device_id))

        sessions.append(
            {
                "patient_id": patient_id,
                "device_id": device_id,
                "timestamp": last.get("timestamp"),
                "age_seconds": round(age, 1) if age is not None else None,
                "mobile_status": link,
                "device_status": device_link,
                "heart_rate_bpm": hr,
                "samples": len(hist),
                "spo2_percent": (last.get("raw_telemetry") or {}).get("spo2_percent"),
                "source": source,
                "ingest_source": source,
            }
        )

    sessions.sort(
        key=lambda s: s.get("age_seconds") if s.get("age_seconds") is not None else 1e12
    )

    online_sessions = [s for s in sessions if s["mobile_status"] == "online"]
    idle_sessions = [s for s in sessions if s["mobile_status"] == "idle"]
    best = (
        online_sessions[0]
        if online_sessions
        else (idle_sessions[0] if idle_sessions else (sessions[0] if sessions else None))
    )

    if online_sessions:
        mobile_overall = "online"
    elif idle_sessions:
        mobile_overall = "idle"
    else:
        mobile_overall = "offline"

    device_overall = _pick_device_overall(sessions, mobile_overall)
    pairing_ready = device_overall in {"ble_sim", "ble_hband"}

    ble_native_done = any(s["device_status"] == "ble_hband" for s in sessions)
    ble_sim_done = any(s["device_status"] == "ble_sim" for s in sessions)

    return {
        "server_time": now.isoformat().replace("+00:00", "Z"),
        "online_threshold_sec": online_threshold_sec,
        "stale_threshold_sec": stale_threshold_sec,
        "mobile_app": {
            "status": mobile_overall,
            "label": MOBILE_LABELS.get(mobile_overall, mobile_overall),
            "active_sessions": len(online_sessions),
            "total_patients": len(sessions),
            "channel": "HTTPS + X-API-Key (OkHttp / Retrofit)",
            "endpoints": [
                "POST /api/v1/wearables/ingest",
                "POST /api/v1/wearables/batch-ingest",
            ],
            "latest": best,
        },
        "device": {
            "status": device_overall,
            "label": DEVICE_LABELS.get(device_overall, device_overall),
            "protocol_current": {
                "ble_hband": "BLE GATT / HBand SDK → app → HTTPS",
                "ble_sim": "Simulador no companion (sem rádio) → HTTPS",
                "via_app": "Ingest HTTP manual / smoke no companion",
                "planned": "Aguardando simulador BLE ou SDK HBand",
                "offline": "Sem telemetria recente",
            }.get(device_overall, "Telemetria via app"),
            "protocol_planned": "BLE GATT / HBand SDK (companion Android)",
            "model_hint": (best or {}).get("device_id") if best else None,
            "pairing_ready": pairing_ready,
            "ble_physical": ble_native_done,
            "ble_simulated": ble_sim_done,
            "roadmap": [
                {"id": "https_ingest", "done": True, "label": "App envia telemetria via HTTPS"},
                {
                    "id": "ble_sim",
                    "done": ble_sim_done,
                    "label": "Simulador BLE no companion (pipeline Device→App)",
                },
                {
                    "id": "ble_hband_sdk",
                    "done": ble_native_done,
                    "label": "Pairing HBand real (SDK Veepoo) — requer AAR + pulseira",
                },
                {
                    "id": "dashboard",
                    "done": True,
                    "label": "Dashboard mostra status honesto (sim vs BLE real)",
                },
            ],
        },
        "pipeline": [
            {"id": "device", "name": "Device (HBand / simulador)", "status": device_overall},
            {"id": "app", "name": "App companion Android", "status": mobile_overall},
            {"id": "api", "name": "Healthtech API", "status": "online"},
            {"id": "dashboard", "name": "Dashboard web", "status": "online"},
        ],
        "sessions": sessions[:20],
    }

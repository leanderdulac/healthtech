"""Detalhe autenticado de um relógio da frota.

Não inclui localização (GPS, aproximada ou nome de município). A região
vem só do cadastro (`enrollments.municipality_id` / `ubs_id`).
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

REGION_SOURCE = "cadastro"
APP_VERSION_MAX_LEN = 64
DEVICE_LABEL_MAX_LEN = 80

_LOCATION_KEYS = frozenset(
    {
        "latitude",
        "longitude",
        "lat",
        "lng",
        "gps",
        "geo",
        "geolocation",
        "location",
        "approx_location",
        "approximate_location",
        "coordinates",
        "coord",
        "municipality_name",
        "ubs_name",
        "city",
        "cidade",
    }
)


def normalize_app_version(value: Any) -> Optional[str]:
    """Header X-App-Version: texto imprimível, curto, sem inventar dado."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    cleaned = "".join(ch for ch in text if ch.isprintable())
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    return cleaned[:APP_VERSION_MAX_LEN]


def normalize_optional_text(value: Any, *, max_len: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:max_len]


def first_app_version(*sources: Any) -> Optional[str]:
    for source in sources:
        found = _pick_from_blobs(source, ("app_version", "X-App-Version", "x-app-version"))
        version = normalize_app_version(found)
        if version:
            return version
    return None


def first_device_label(*sources: Any) -> Optional[str]:
    for source in sources:
        found = _pick_from_blobs(source, ("device_label", "device_name"))
        label = normalize_optional_text(found, max_len=DEVICE_LABEL_MAX_LEN)
        if label:
            return label
    return None


def first_ingest_source(*sources: Any) -> Optional[str]:
    for source in sources:
        found = _pick_from_blobs(source, ("ingest_source",))
        source_name = normalize_optional_text(found, max_len=32)
        if source_name:
            return source_name
    return None


def attach_app_version(
    frame: Dict[str, Any],
    extra: Optional[Dict[str, Any]],
    header_value: Any = None,
) -> Dict[str, Any]:
    """Grava a versão do app em extra + frame quando o header (ou o body) trouxe."""
    extra_out = dict(extra or {})
    version = normalize_app_version(header_value) or first_app_version(
        extra_out, frame, frame.get("extra"), frame.get("raw_telemetry")
    )
    if not version:
        return extra_out
    extra_out["app_version"] = version
    frame["app_version"] = version
    nested = dict(frame.get("extra") or extra_out)
    nested["app_version"] = version
    frame["extra"] = nested
    return extra_out


def lookup_device_row(device_id: str) -> Optional[Dict[str, Any]]:
    wanted = (device_id or "").strip()
    if not wanted:
        return None

    try:
        from src.ops.device_registry import get_device

        row = get_device(wanted)
        if row and str(row.get("device_id") or "") == wanted:
            return row
    except Exception:
        pass

    try:
        from app.services import telemetry_store

        payload = telemetry_store.list_devices(
            q=wanted,
            include_latest=True,
            include_synthetic=True,
            limit=500,
        )
        match = _exact_device(payload.get("devices"), wanted)
        if match is not None:
            return match
    except Exception:
        pass

    try:
        from src.ops.dashboard_fleet import present_fleet

        payload = present_fleet(
            q=wanted,
            include_latest=True,
            include_synthetic=True,
            limit=500,
        )
        match = _exact_device(payload.get("devices"), wanted)
        if match is not None:
            return match
    except Exception:
        pass
    return None


def enrollment_region(patient_id: Optional[str]) -> Dict[str, Any]:
    """IDs do cadastro. Sem nomes, sem GPS. Falha de banco → IDs ausentes."""
    region: Dict[str, Any] = {
        "municipality_id": None,
        "ubs_id": None,
        "source": REGION_SOURCE,
    }
    pid = (patient_id or "").strip()
    if not pid:
        return region
    try:
        from src.ops.operational_patients import OperationalDbUnavailable, get_patient

        patient = get_patient(pid)
    except OperationalDbUnavailable:
        return region
    except Exception:
        return region
    if not isinstance(patient, dict):
        return region
    region["municipality_id"] = _id_or_none(patient.get("municipality_id"))
    region["ubs_id"] = _id_or_none(patient.get("ubs_id"))
    return region


def build_device_detail(row: Mapping[str, Any]) -> Dict[str, Any]:
    latest = row.get("latest") if isinstance(row.get("latest"), dict) else {}
    extra = latest.get("extra") if isinstance(latest.get("extra"), dict) else {}
    if not extra and isinstance(row.get("extra"), dict):
        extra = row.get("extra") or {}
    raw = latest.get("raw_telemetry") if isinstance(latest.get("raw_telemetry"), dict) else {}
    patient_id = row.get("patient_id") or latest.get("patient_id")
    payload = {
        "ok": True,
        "device_id": row.get("device_id"),
        "device_label": first_device_label(row, latest, extra, raw),
        "device_model": normalize_optional_text(
            row.get("device_model") or raw.get("device_model"),
            max_len=80,
        ),
        "patient_id": patient_id,
        "ingest_source": first_ingest_source(row, latest, extra, raw),
        "last_seen": row.get("last_seen") or latest.get("last_seen") or latest.get("timestamp"),
        "last_seen_local": row.get("last_seen_local") or latest.get("last_seen_local"),
        "received_at": row.get("received_at") or latest.get("received_at"),
        "online": bool(row.get("online")),
        "app_version": first_app_version(row, latest, extra, raw),
        "vitals": {
            "heart_rate": row.get("heart_rate"),
            "spo2": row.get("spo2"),
            "steps": row.get("steps"),
            "blood_pressure_sys": row.get("blood_pressure_sys"),
            "blood_pressure_dia": row.get("blood_pressure_dia"),
        },
        "region": enrollment_region(str(patient_id) if patient_id is not None else None),
    }
    return _strip_location(payload)


def _exact_device(rows: Any, device_id: str) -> Optional[Dict[str, Any]]:
    if not isinstance(rows, list):
        return None
    for item in rows:
        if isinstance(item, dict) and str(item.get("device_id") or "") == device_id:
            return item
    return None


def _id_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _pick_from_blobs(source: Any, keys: tuple[str, ...]) -> Any:
    blobs = _blobs(source)
    for blob in blobs:
        for key in keys:
            if key in blob and blob.get(key) not in (None, ""):
                return blob.get(key)
    return None


def _blobs(source: Any) -> tuple[Dict[str, Any], ...]:
    if not isinstance(source, dict):
        return ()
    extra = source.get("extra") if isinstance(source.get("extra"), dict) else None
    raw = source.get("raw_telemetry") if isinstance(source.get("raw_telemetry"), dict) else None
    parts = [source]
    if extra is not None:
        parts.append(extra)
    if raw is not None:
        parts.append(raw)
    return tuple(parts)


def _strip_location(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Garante que o detalhe autenticado também não vaze GPS/nomes de lugar."""
    clean = {key: value for key, value in payload.items() if key not in _LOCATION_KEYS}
    region = clean.get("region")
    if isinstance(region, dict):
        clean["region"] = {
            "municipality_id": _id_or_none(region.get("municipality_id")),
            "ubs_id": _id_or_none(region.get("ubs_id")),
            "source": REGION_SOURCE,
        }
    return clean

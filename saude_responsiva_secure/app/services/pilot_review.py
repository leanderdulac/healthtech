"""Registro do piloto: o que a regra mostrou e a marca humana, quando houver.

O arquivo é local (JSONL). ble_sim e ingest manual entram no registro com
pilot_eligible=false e ficam de fora da taxa de alarme falso.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

MARKS = frozenset({"correct", "false_alarm", "missed"})


def review_path() -> Path:
    return Path(os.getenv("PILOT_REVIEW_PATH", "data/pilot_review/events.jsonl"))


def _load(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    target = path or review_path()
    if not target.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _write(rows: List[Dict[str, Any]], path: Optional[Path] = None) -> None:
    target = path or review_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    target.write_text(body, encoding="utf-8")


def record_ingest(frame: Dict[str, Any], path: Optional[Path] = None) -> Optional[str]:
    """Grava um evento de ingestão já avaliado só por regras. Devolve o id."""
    alerts = frame.get("clinical_alerts") or {}
    if not isinstance(alerts, dict) or alerts.get("engine") != "alert_matrix_rules":
        return None
    event_id = uuid.uuid4().hex
    provenance = alerts.get("provenance") if isinstance(alerts.get("provenance"), dict) else {}
    row = {
        "event_id": event_id,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "patient_id": frame.get("patient_id"),
        "device_id": frame.get("device_id"),
        "timestamp": frame.get("timestamp") or frame.get("received_at"),
        "ingest_source": alerts.get("ingest_source") or frame.get("ingest_source"),
        "pilot_eligible": bool(alerts.get("pilot_eligible")),
        "is_true_alert": bool(alerts.get("is_true_alert")),
        "severity": alerts.get("severity"),
        "primary_rule_id": alerts.get("primary_rule_id"),
        "primary_alert_name": alerts.get("primary_alert_name"),
        "decision": alerts.get("decision"),
        "git_sha": provenance.get("git_sha"),
        "rules_sha256": provenance.get("rules_sha256"),
        "matrix_version": alerts.get("matrix_version"),
        "mark": None,
    }
    rows = _load(path)
    rows.append(row)
    _write(rows, path)
    return event_id


def purge_patient(patient_id: str, path: Optional[Path] = None) -> int:
    """Tira deste arquivo as linhas do paciente. Devolve quantas saíram."""
    wanted = (patient_id or "").strip()
    if not wanted:
        return 0
    rows = _load(path)
    kept = [row for row in rows if str(row.get("patient_id") or "") != wanted]
    removed = len(rows) - len(kept)
    if removed:
        _write(kept, path)
    return removed


def mark_event(event_id: str, mark: str, path: Optional[Path] = None) -> bool:
    if mark not in MARKS:
        raise ValueError("marca inválida. Use correct, false_alarm ou missed.")
    rows = _load(path)
    found = False
    for row in rows:
        if row.get("event_id") == event_id:
            row["mark"] = mark
            row["marked_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            found = True
            break
    if found:
        _write(rows, path)
    return found


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def summary(path: Optional[Path] = None) -> Dict[str, Any]:
    """Alarmes falsos por 24 h só entre eventos elegíveis e já marcados."""
    rows = _load(path)
    eligible = [r for r in rows if r.get("pilot_eligible")]
    marked = [r for r in eligible if r.get("mark")]
    false_alarms = [r for r in marked if r.get("mark") == "false_alarm"]
    rules: Dict[str, int] = {}
    for row in eligible:
        if row.get("is_true_alert") and row.get("primary_rule_id"):
            rid = str(row["primary_rule_id"])
            rules[rid] = rules.get(rid, 0) + 1
    stamps = [ts for ts in (_parse_ts(r.get("timestamp")) for r in eligible) if ts]
    window_hours = None
    per_24h = None
    if len(stamps) >= 2:
        window_hours = round((max(stamps) - min(stamps)).total_seconds() / 3600.0, 2)
        if window_hours > 0 and marked:
            per_24h = round(len(false_alarms) * 24.0 / window_hours, 2)
    return {
        "events": len(rows),
        "pilot_eligible": len(eligible),
        "excluded": len(rows) - len(eligible),
        "marked": len(marked),
        "false_alarms": len(false_alarms),
        "window_hours": window_hours,
        "false_alarms_per_24h": per_24h,
        "rules_fired": rules,
        "note": (
            "A taxa usa só ble_hband e ble_standard com marca humana. "
            "ble_sim e HTTP manual ficam em excluded."
        ),
    }

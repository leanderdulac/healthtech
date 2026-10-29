"""Decisão do TCN multi-horizonte.

A calibração em `conformal_calibration.json` está degenerada: q_hat 1 em 6h
e 0 em 24h. A validação de 05/07/2026 (5 pacientes, F1 médio 0,64) não
autoriza alerta clínico. A resposta leva as probabilidades e não promove
alerta nem intervalo enquanto os três horizontes não tiverem q_hat em (0, 1).
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence

HORIZON_LABELS = ("6h", "24h", "72h")
HORIZON_NAMES = ("event_6h", "event_24h", "event_72h")


def q_hat(conformal: Optional[Mapping], index: int) -> Optional[float]:
    if not conformal:
        return None
    name = HORIZON_NAMES[index]
    horizons = conformal.get("horizons") or {}
    bucket = horizons.get(name) if isinstance(horizons, Mapping) else None
    if isinstance(bucket, Mapping) and bucket.get("q_hat") is not None:
        return float(bucket["q_hat"])
    q_map = conformal.get("q_hat")
    if isinstance(q_map, Mapping) and q_map.get(name) is not None:
        return float(q_map[name])
    return None


def q_hat_usable(value: Optional[float]) -> bool:
    return value is not None and 0.0 < float(value) < 1.0


def calibration_usable(conformal: Optional[Mapping]) -> bool:
    if not conformal:
        return False
    return all(q_hat_usable(q_hat(conformal, i)) for i in range(3))


def decide_tcn(probs: Sequence[float], conformal: Optional[Mapping]) -> Dict:
    """Probabilidades entram. Alerta clínico não sai desta calibração."""
    rounded: List[float] = [round(float(p), 4) for p in list(probs)[:3]]
    while len(rounded) < 3:
        rounded.append(0.0)
    usable = calibration_usable(conformal)
    decision = {
        "prob_6h": rounded[0],
        "prob_24h": rounded[1],
        "prob_72h": rounded[2],
        "max_probability": round(max(rounded), 4),
        "horizon_at_risk": None,
        "alerta": False,
        "uso": "laboratorio",
        "conformal_status": "calibrado" if usable else ("degenerado" if conformal else "ausente"),
    }
    if not usable:
        return decision
    intervals = {}
    for i, label in enumerate(HORIZON_LABELS):
        width = float(q_hat(conformal, i))
        probability = rounded[i]
        intervals[label] = [
            round(max(0.0, probability - width), 4),
            round(min(1.0, probability + width), 4),
        ]
    decision["conformal_intervals"] = intervals
    return decision

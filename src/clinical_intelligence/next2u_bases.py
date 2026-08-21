"""
158 alertas-base Next2U (predicados fisiológicos).

Fonte: matriz expandida 16/08/2026. A promoção por estrelas é feita
depois, em next2u_promotion — aqui só o padrão original.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.clinical_intelligence.alert_matrix_rules import VitalSnapshot, _ge, _in, _le

Pred = Callable[[VitalSnapshot], bool]
STAR_SEV = {1: "leve", 2: "moderado", 3: "critico"}
PROFILE_CAT = {
    1: "pa_alta",
    2: "pa_baixa",
    3: "spo2",
    4: "temperatura",
    5: "hipoglicemia",
    6: "hiperglicemia",
    7: "fc",
    8: "fc",
    9: "funcional",
    10: "infeccao",
    11: "desidratacao",
    12: "queda",
}


def _nvitals_abnormal(v: VitalSnapshot) -> int:
    n = 0
    if v.pas is not None and (v.pas >= 140 or v.pas <= 100):
        n += 1
    if v.hr is not None and (v.hr >= 111 or v.hr <= 50):
        n += 1
    if v.spo2 is not None and v.spo2 <= 94:
        n += 1
    if v.temp_c is not None and (v.temp_c >= 38.1 or v.temp_c <= 36.0):
        n += 1
    if v.glucose_mgdl is not None and (v.glucose_mgdl >= 181 or v.glucose_mgdl < 70):
        n += 1
    return n


def _build_preds() -> Dict[int, Pred]:
    P: Dict[int, Pred] = {}

    def add(i: int, fn: Pred) -> None:
        P[i] = fn

    # --- Perfil 1 PA elevada ---
    add(1, lambda v: _in(v.pas, 140, 159) and _in(v.pad, 90, 99) and _in(v.hr, 91, 110))
    add(2, lambda v: _in(v.pas, 160, 179) and _in(v.pad, 100, 109) and _in(v.hr, 111, 130))
    add(3, lambda v: _ge(v.pas, 180) and _ge(v.pad, 110) and _ge(v.hr, 111))
    add(4, lambda v: _ge(v.pas, 180) and _ge(v.pad, 110) and _le(v.spo2, 93))
    add(5, lambda v: _ge(v.pas, 180) and _ge(v.pad, 110) and _ge(v.temp_c, 38.1))
    add(6, lambda v: _ge(v.pas, 180) and _ge(v.pad, 110) and _ge(v.glucose_mgdl, 250))
    add(7, lambda v: _in(v.pas, 140, 159) and _in(v.pad, 90, 99))
    add(8, lambda v: _in(v.pas, 160, 179) and _in(v.pad, 100, 109))
    add(9, lambda v: _in(v.pas, 160, 179) and _in(v.pad, 100, 109) and _in(v.spo2, 93, 94))
    add(
        10,
        lambda v: (
            (v.pas_rise() is not None and v.pas_rise() >= 30)
            or (v.pad_rise() is not None and v.pad_rise() >= 20)
        )
        and _in(v.hr, 91, 110),
    )
    add(11, lambda v: _in(v.pas, 130, 139) or _in(v.pad, 80, 89))
    add(12, lambda v: _in(v.pas, 140, 159) and (v.pad is not None and v.pad < 90))
    add(13, lambda v: _in(v.pad, 90, 99) and (v.pas is not None and v.pas < 140))
    add(14, lambda v: _in(v.pas, 160, 179) and (v.pad is not None and v.pad < 100))
    add(15, lambda v: _in(v.pad, 100, 109) and (v.pas is not None and v.pas < 160))

    # --- Perfil 2 PA baixa ---
    add(16, lambda v: _in(v.pas, 101, 110) and _in(v.hr, 91, 110))
    add(17, lambda v: _in(v.pas, 91, 100) and _in(v.hr, 111, 130))
    add(18, lambda v: _in(v.pas, 91, 100) and _ge(v.hr, 111) and _ge(v.temp_c, 38.1))
    add(19, lambda v: _in(v.pas, 91, 100) and _ge(v.hr, 111) and _le(v.spo2, 93))
    add(20, lambda v: _le(v.pas, 90) and _ge(v.hr, 111))
    add(21, lambda v: _le(v.pas, 90) and _le(v.spo2, 91))
    add(22, lambda v: _in(v.pas, 101, 110))
    add(23, lambda v: _in(v.pas, 91, 100))
    add(24, lambda v: _in(v.pas, 91, 100) and _in(v.hr, 91, 110))
    add(25, lambda v: _in(v.pas, 91, 100) and _in(v.spo2, 93, 94))
    add(26, lambda v: _in(v.pas, 101, 110))
    add(27, lambda v: _in(v.pas, 91, 100))
    add(
        28,
        lambda v: v.pas_drop() is not None
        and v.pas_drop() >= 20
        and _in(v.pas, 101, 110),
    )
    add(
        29,
        lambda v: v.pas_drop() is not None
        and v.pas_drop() >= 30
        and _in(v.pas, 91, 110),
    )

    # --- Perfil 3 SpO2 ---
    add(30, lambda v: _in(v.spo2, 95, 96))
    add(31, lambda v: _in(v.spo2, 93, 94))
    add(32, lambda v: _in(v.spo2, 93, 94) and _in(v.hr, 111, 130))
    add(33, lambda v: _in(v.spo2, 92, 93) and _ge(v.hr, 111) and _ge(v.temp_c, 38.1))
    add(34, lambda v: _le(v.spo2, 91))
    add(35, lambda v: _le(v.spo2, 91) and _ge(v.hr, 111))
    add(36, lambda v: _le(v.spo2, 91) and _ge(v.temp_c, 38.1))
    add(37, lambda v: _in(v.spo2, 95, 96) and _in(v.hr, 91, 110))
    add(
        38,
        lambda v: _ge(v.spo2_drop_points, 2) and (v.spo2 is not None and v.spo2 >= 95),
    )
    add(39, lambda v: _in(v.spo2, 93, 94) and _in(v.temp_c, 38.1, 39.0))
    add(40, lambda v: _in(v.spo2, 93, 94) and _ge(v.steps_drop_pct, 40))
    add(41, lambda v: _ge(v.spo2_drop_points, 3))
    add(42, lambda v: v.spo2 is not None and abs(v.spo2 - 92.0) < 0.51)
    add(43, lambda v: _in(v.spo2, 95, 96) and (v.consecutive_valid or 1) >= 2)
    add(
        44,
        lambda v: _ge(v.spo2_drop_points, 3) and _in(v.spo2, 93, 94),
    )

    # --- Perfil 4 temperatura ---
    add(45, lambda v: _in(v.temp_c, 38.1, 39.0) and _in(v.hr, 91, 110))
    add(46, lambda v: _in(v.temp_c, 38.1, 39.0) and _in(v.hr, 111, 130))
    add(47, lambda v: _in(v.temp_c, 38.1, 39.0) and _ge(v.hr, 111) and _le(v.spo2, 93))
    add(48, lambda v: _in(v.temp_c, 38.1, 39.0) and _ge(v.hr, 111) and _le(v.pas, 100))
    add(49, lambda v: _ge(v.temp_c, 39.1) and _ge(v.hr, 111))
    add(
        50,
        lambda v: _ge(v.temp_c, 39.1)
        and _ge(v.hr, 111)
        and (_le(v.pas, 100) or _le(v.spo2, 93)),
    )
    add(51, lambda v: _le(v.temp_c, 35.0) and (_le(v.hr, 50) or _le(v.pas, 100)))
    add(52, lambda v: _in(v.temp_c, 38.1, 39.0))
    add(53, lambda v: _in(v.temp_c, 35.1, 36.0))
    add(
        54,
        lambda v: _in(v.temp_c, 35.1, 36.0)
        and (_in(v.hr, 41, 50) or _in(v.pas, 101, 110)),
    )
    add(55, lambda v: _in(v.temp_c, 38.1, 39.0) and _in(v.spo2, 93, 94))
    add(
        56,
        lambda v: (v.temp_rise() is not None and v.temp_rise() >= 1.0)
        and _ge(v.hr_baseline_rise, 15),
    )
    add(57, lambda v: _in(v.temp_c, 38.1, 39.0))
    add(58, lambda v: _ge(v.temp_c, 39.1))
    add(59, lambda v: _in(v.temp_c, 35.1, 36.0))
    add(
        60,
        lambda v: (v.temp_drop() is not None and v.temp_drop() >= 1.0)
        and _in(v.temp_c, 35.1, 36.0),
    )

    # --- Perfil 5 hipoglicemia ---
    add(61, lambda v: _in(v.glucose_mgdl, 54, 69))
    add(62, lambda v: _in(v.glucose_mgdl, 54, 69) and _ge(v.hr, 111))
    add(63, lambda v: _in(v.glucose_mgdl, 54, 69) and _le(v.pas, 100))
    add(64, lambda v: v.glucose_mgdl is not None and v.glucose_mgdl < 54)
    add(
        65,
        lambda v: (v.glucose_mgdl is not None and v.glucose_mgdl < 54)
        and (
            v.consciousness_altered
            or _ge(v.hr, 91)
            or _le(v.hr, 50)
            or _le(v.pas, 100)
            or _ge(v.pas, 140)
        ),
    )
    add(
        66,
        lambda v: _in(v.glucose_mgdl, 70, 79)
        and (v.glucose_delta() is not None and v.glucose_delta() < 0)
        and (v.consecutive_valid or 1) >= 2,
    )
    add(67, lambda v: _in(v.glucose_mgdl, 70, 79) and _in(v.hr, 91, 110))
    add(
        68,
        lambda v: (v.glucose_delta() is not None and v.glucose_delta() <= -30)
        and _in(v.glucose_mgdl, 70, 89),
    )
    add(69, lambda v: _in(v.glucose_mgdl, 54, 69) and (v.consecutive_valid or 1) >= 2)
    add(70, lambda v: _in(v.glucose_mgdl, 70, 79))
    add(71, lambda v: _in(v.glucose_mgdl, 70, 79) and (v.consecutive_valid or 1) >= 2)
    add(
        72,
        lambda v: (v.glucose_vs_basal() is not None and -29 <= v.glucose_vs_basal() <= -20)
        and _in(v.glucose_mgdl, 70, 89),
    )

    # --- Perfil 6 hiperglicemia ---
    add(73, lambda v: _in(v.glucose_mgdl, 181, 249))
    add(74, lambda v: _in(v.glucose_mgdl, 250, 399))
    add(75, lambda v: _in(v.glucose_mgdl, 250, 399) and _ge(v.temp_c, 38.1))
    add(
        76,
        lambda v: _in(v.glucose_mgdl, 250, 399) and _ge(v.temp_c, 38.1) and _ge(v.hr, 111),
    )
    add(77, lambda v: _in(v.glucose_mgdl, 250, 399) and _ge(v.hr, 111) and _le(v.pas, 100))
    add(78, lambda v: _ge(v.glucose_mgdl, 400) and (v.glucose_mgdl is None or v.glucose_mgdl < 600))
    add(79, lambda v: _ge(v.glucose_mgdl, 600))
    add(
        80,
        lambda v: (v.glucose_vs_basal() is not None and v.glucose_vs_basal() >= 50)
        and _in(v.glucose_mgdl, 181, 249),
    )
    add(81, lambda v: _in(v.glucose_mgdl, 181, 249) and (v.consecutive_valid or 1) >= 2)
    add(82, lambda v: _in(v.glucose_mgdl, 181, 249) and _in(v.hr, 91, 110))
    add(83, lambda v: _in(v.glucose_mgdl, 181, 249) and _in(v.temp_c, 38.1, 39.0))
    add(84, lambda v: _in(v.glucose_mgdl, 181, 249) and _ge(v.steps_drop_pct, 40))
    add(85, lambda v: _in(v.glucose_mgdl, 140, 180) and v.fasting)
    add(
        86,
        lambda v: (v.glucose_vs_basal() is not None and 30 <= v.glucose_vs_basal() <= 49)
        and _in(v.glucose_mgdl, 181, 249),
    )

    # --- Perfil 7/8 FC ---
    add(87, lambda v: _in(v.hr, 41, 50))
    add(88, lambda v: _in(v.hr, 41, 50) and _le(v.pas, 100))
    add(89, lambda v: _in(v.hr, 41, 50) and _le(v.spo2, 93))
    add(90, lambda v: _le(v.hr, 40))
    add(91, lambda v: _in(v.hr, 111, 130))
    add(92, lambda v: _ge(v.hr, 131))
    add(
        93,
        lambda v: _ge(v.hr, 131)
        and (
            _ge(v.pas, 140)
            or _le(v.pas, 100)
            or _le(v.spo2, 96)
            or _ge(v.temp_c, 38.1)
            or _le(v.temp_c, 35.0)
        ),
    )
    add(94, lambda v: _in(v.hr, 91, 110) and v.rest)
    add(95, lambda v: _ge(v.hr_baseline_rise, 15) and v.rest)
    add(96, lambda v: _in(v.hr, 111, 130) and v.rest)
    add(97, lambda v: _in(v.hr, 91, 110) and _in(v.temp_c, 38.1, 39.0))
    add(98, lambda v: _in(v.hr, 91, 110) and _in(v.spo2, 93, 94))
    add(
        99,
        lambda v: _in(v.hr, 51, 60)
        and v.rest
        and v.hr_baseline_rise is not None
        and v.hr_baseline_rise <= -10,
    )
    add(100, lambda v: _in(v.hr, 91, 110) and v.rest)
    add(
        101,
        lambda v: _ge(v.hr_baseline_rise, 20) and _in(v.hr, 91, 110),
    )
    add(
        102,
        lambda v: _ge(v.hr_baseline_rise, 30) and _in(v.hr, 111, 130),
    )

    # --- Perfil 9 funcional/sono ---
    add(103, lambda v: _ge(v.steps_drop_pct, 40) and _ge(v.sleep_worsen_pct, 30))
    add(
        104,
        lambda v: _ge(v.steps_drop_pct, 40)
        and _ge(v.sleep_worsen_pct, 30)
        and _ge(v.hr_baseline_rise, 15),
    )
    add(105, lambda v: _ge(v.steps_drop_pct, 50) and _ge(v.spo2_drop_points, 3))
    add(
        106,
        lambda v: (_ge(v.steps_drop_pct, 40) or _ge(v.sleep_worsen_pct, 30))
        and (
            _ge(v.temp_c, 38.1)
            or _le(v.spo2, 93)
            or _le(v.pas, 100)
            or _ge(v.hr, 111)
        ),
    )
    add(
        107,
        lambda v: _ge(v.sleep_worsen_pct, 30)
        and _in(v.pas, 140, 159)
        and _in(v.pad, 90, 99)
        and _in(v.hr, 91, 110),
    )
    add(
        108,
        lambda v: _ge(v.sleep_worsen_pct, 30)
        and (
            (_in(v.pas, 160, 179) and _in(v.pad, 100, 109)) or _in(v.hr, 111, 130)
        ),
    )
    add(
        109,
        lambda v: _in(v.steps_drop_pct, 20, 39)
        and _in(v.sleep_worsen_pct, 20, 29)
        and (v.steps_drop_days or 0) >= 2,
    )
    add(110, lambda v: _ge(v.steps_drop_pct, 30) and (v.steps_drop_days or 0) >= 3)
    add(
        111,
        lambda v: (
            (v.sleep_hours is not None and v.sleep_hours < 6 and (v.consecutive_valid or 1) >= 2)
            or _ge(v.sleep_worsen_pct, 30)
        ),
    )
    add(
        112,
        lambda v: _ge(v.sleep_worsen_pct, 30) and _in(v.hr_baseline_rise, 10, 14),
    )
    add(
        113,
        lambda v: (v.sleep_hours is not None and v.sleep_hours < 5)
        and (v.consecutive_valid or 1) >= 2
        and _ge(v.hr_baseline_rise, 10),
    )
    add(114, lambda v: _ge(v.sleep_worsen_pct, 40) and _ge(v.spo2_drop_points, 2))
    add(115, lambda v: _ge(v.steps_drop_pct, 40) and _in(v.pas, 91, 100))
    add(116, lambda v: _ge(v.steps_drop_pct, 40) and _in(v.temp_c, 38.1, 39.0))

    # --- Perfil 10 infecção ---
    add(
        117,
        lambda v: _in(v.temp_c, 38.1, 39.0)
        and (v.spo2 is not None and v.spo2 >= 95)
        and _in(v.hr, 91, 110),
    )
    add(118, lambda v: _in(v.temp_c, 38.1, 39.0) and _in(v.steps_drop_pct, 20, 39))
    add(
        119,
        lambda v: (v.temp_rise() is not None and v.temp_rise() >= 1.0)
        and _ge(v.hr_baseline_rise, 15),
    )
    add(
        120,
        lambda v: _in(v.temp_c, 38.1, 39.0)
        and (v.spo2 is not None and v.spo2 >= 95)
        and _in(v.hr, 111, 130),
    )
    add(121, lambda v: _in(v.temp_c, 38.1, 39.0) and _in(v.spo2, 93, 94))
    add(
        122,
        lambda v: _in(v.spo2, 93, 94) and _in(v.hr, 111, 130) and _ge(v.steps_drop_pct, 40),
    )
    add(123, lambda v: _in(v.temp_c, 38.1, 39.0) and _in(v.glucose_mgdl, 250, 399))
    add(124, lambda v: _ge(v.temp_c, 39.1) and _in(v.hr, 111, 130))
    add(
        125,
        lambda v: _in(v.temp_c, 35.1, 36.0)
        and _in(v.hr, 91, 130)
        and _ge(v.steps_drop_pct, 40),
    )
    add(126, lambda v: _in(v.temp_c, 38.1, 39.0) and _ge(v.hr, 131) and _in(v.pas, 91, 100))
    add(127, lambda v: _in(v.temp_c, 38.1, 39.0) and _le(v.spo2, 91) and _ge(v.hr, 111))
    add(128, lambda v: _le(v.temp_c, 35.0) and (_ge(v.hr, 111) or _le(v.pas, 100)))
    add(
        129,
        lambda v: _le(v.pas, 90)
        and _ge(v.hr, 111)
        and (_ge(v.temp_c, 38.1) or _le(v.temp_c, 36.0)),
    )
    add(
        130,
        lambda v: _le(v.spo2, 91)
        and _le(v.pas, 100)
        and _ge(v.hr, 111)
        and (
            (v.temp_c is not None and v.temp_c >= 38.1)
            or (v.temp_c is not None and v.temp_c <= 36.0)
        ),
    )

    # --- Perfil 11 desidratação ---
    add(131, lambda v: _in(v.hr, 91, 110) and _ge(v.hr_baseline_rise, 15))
    add(132, lambda v: _in(v.pas, 101, 110) and _in(v.hr, 91, 110))
    add(
        133,
        lambda v: (v.pas_drop() is not None and v.pas_drop() >= 20)
        and _in(v.pas, 101, 110)
        and _ge(v.hr_baseline_rise, 15),
    )
    add(
        134,
        lambda v: _in(v.pas, 101, 110)
        and _in(v.hr, 91, 110)
        and (v.consecutive_valid or 1) >= 2,
    )
    add(135, lambda v: _in(v.pas, 91, 100) and _in(v.hr, 91, 110))
    add(136, lambda v: _in(v.pas, 91, 100) and _in(v.hr, 111, 130))
    add(
        137,
        lambda v: (v.pas_drop() is not None and v.pas_drop() >= 30)
        and _ge(v.hr_baseline_rise, 20),
    )
    add(138, lambda v: _ge(v.steps_drop_pct, 40) and _in(v.pas, 91, 100))
    add(
        139,
        lambda v: _in(v.glucose_mgdl, 250, 399)
        and _in(v.hr, 111, 130)
        and _ge(v.steps_drop_pct, 40),
    )
    add(140, lambda v: _ge(v.temp_c, 39.1) and _in(v.hr, 111, 130))
    add(141, lambda v: _le(v.pas, 90) and _ge(v.hr, 111))
    add(142, lambda v: _le(v.pas, 90) and _ge(v.steps_drop_pct, 50))
    add(143, lambda v: _ge(v.glucose_mgdl, 400) and _ge(v.hr, 111) and _le(v.pas, 100))
    add(144, lambda v: _ge(v.temp_c, 39.1) and _ge(v.hr, 131) and _le(v.pas, 100))

    # --- Perfil 12 queda / síncope ---
    add(145, lambda v: _in(v.steps_drop_pct, 40, 49))
    add(146, lambda v: v.steps_interrupted)
    add(
        147,
        lambda v: _ge(v.steps_drop_pct, 40) and _ge(v.sleep_worsen_pct, 30),
    )
    add(148, lambda v: v.steps_interrupted and _ge(v.hr_baseline_rise, 15))
    add(
        149,
        lambda v: v.steps_interrupted
        and (v.pas_drop() is not None and v.pas_drop() >= 20),
    )
    add(150, lambda v: _ge(v.steps_drop_pct, 50) and _in(v.pas, 91, 100))
    add(151, lambda v: v.steps_interrupted and _in(v.hr, 111, 130))
    add(
        152,
        lambda v: v.steps_interrupted
        and _ge(v.spo2_drop_points, 3)
        and _in(v.spo2, 93, 94),
    )
    add(
        153,
        lambda v: v.no_steps_rest_of_active and _nvitals_abnormal(v) >= 2,
    )
    add(154, lambda v: _le(v.pas, 90) and v.steps_interrupted)
    add(155, lambda v: _ge(v.hr, 131) and v.steps_interrupted)
    add(156, lambda v: _le(v.spo2, 91) and v.steps_interrupted)
    add(157, lambda v: _le(v.hr, 50) and _le(v.pas, 100) and v.steps_interrupted)
    add(
        158,
        lambda v: (v.glucose_mgdl is not None and v.glucose_mgdl < 54)
        and v.steps_interrupted,
    )
    return P


PREDICATES: Dict[int, Pred] = _build_preds()


def _short_name(suggested: str) -> str:
    return re.sub(
        r"\s*-\s*(baixo risco|risco moderado.*|alto risco.*|risco crítico.*)$",
        "",
        suggested or "",
        flags=re.I,
    ).strip()


def load_base_meta(catalog_path: Optional[Path] = None) -> Dict[int, Dict[str, Any]]:
    path = catalog_path or Path("data/models/next2u_expanded_matrix.json")
    cat = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"patterns": []}
    meta: Dict[int, Dict[str, Any]] = {}
    for p in cat.get("patterns", []):
        b = int(p["base_id"])
        if b not in meta:
            meta[b] = {
                "base_id": b,
                "profile_id": int(p["profile_id"]),
                "pattern": p["original_pattern"],
                "base_stars": int(p["stars"]),
                "name": _short_name(p["suggested_name"]),
            }
        else:
            meta[b]["base_stars"] = min(meta[b]["base_stars"], int(p["stars"]))
            if p.get("variant") == 1:
                meta[b]["name"] = _short_name(p["suggested_name"])
                meta[b]["pattern"] = p["original_pattern"]
    return meta


def build_rules() -> List[Dict[str, Any]]:
    meta = load_base_meta()
    rules: List[Dict[str, Any]] = []
    for i in range(1, 159):
        pred = PREDICATES.get(i)
        if pred is None:
            continue
        m = meta.get(i, {})
        stars = int(m.get("base_stars") or 1)
        profile = int(m.get("profile_id") or 1)
        rules.append(
            {
                "rule_id": f"n2u_{i:03d}",
                "category": PROFILE_CAT.get(profile, "clinico"),
                "severity": STAR_SEV.get(stars, "leve"),
                "name": m.get("name") or f"Possível padrão clínico {i:03d}",
                "predicate": pred,
                "next2u_base": i,
                "profile_id": profile,
            }
        )
    return rules


def next2u_mapping() -> Dict[str, Tuple[int, int]]:
    meta = load_base_meta()
    out: Dict[str, Tuple[int, int]] = {}
    for i in range(1, 159):
        profile = int(meta.get(i, {}).get("profile_id") or 1)
        out[f"n2u_{i:03d}"] = (profile, i)
    # aliases do motor antigo
    legacy = {
        "pa_elev_1": 1, "pa_elev_2": 2, "pa_elev_3": 3, "pa_elev_4": 4,
        "pa_elev_5": 5, "pa_elev_6": 6,
        "pa_baixa_1": 16, "pa_baixa_2": 17, "pa_baixa_3": 18, "pa_baixa_4": 19,
        "pa_baixa_5": 20, "pa_baixa_6": 21,
        "spo2_1": 30, "spo2_2": 31, "spo2_3": 32, "spo2_4": 33, "spo2_5": 34,
        "spo2_6": 35, "spo2_7": 36,
        "temp_1": 45, "temp_2": 46, "temp_3": 47, "temp_4": 48, "temp_5": 49,
        "temp_6": 50, "temp_7": 51,
        "hypo_1": 61, "hypo_2": 62, "hypo_3": 63, "hypo_4": 64, "hypo_5": 65,
        "hyper_1": 73, "hyper_2": 74, "hyper_3": 75, "hyper_4": 76,
        "hyper_5": 77, "hyper_6": 78, "hyper_7": 79,
        "fc_1": 87, "fc_2": 88, "fc_3": 89, "fc_4": 90, "fc_5": 91,
        "fc_6": 92, "fc_7": 93,
        "func_1": 103, "func_2": 104, "func_3": 105, "func_4": 106,
        "func_5": 107, "func_6": 108,
    }
    for rid, base in legacy.items():
        out[rid] = out[f"n2u_{base:03d}"]
    return out


def sample_for_base(base_id: int, rng: Any) -> VitalSnapshot:
    """Amostra que tenta satisfazer o predicado do alerta-base."""
    pred = PREDICATES[base_id]
    u = rng.uniform
    for _ in range(120):
        v = VitalSnapshot(
            pas=u(70, 210),
            pad=u(40, 130),
            hr=u(35, 165),
            spo2=u(82, 100),
            temp_c=u(34.4, 40.6),
            glucose_mgdl=u(35, 680),
            steps_drop_pct=u(0, 85),
            sleep_worsen_pct=u(0, 75),
            hr_baseline_rise=u(-25, 45),
            spo2_drop_points=u(0, 10),
            consciousness_altered=rng.random() < 0.12,
            pas_basal=u(108, 145),
            pad_basal=u(68, 92),
            spo2_basal=u(95, 99),
            temp_basal=u(36.1, 37.3),
            glucose_basal=u(80, 170),
            glucose_prev=u(60, 260),
            consecutive_valid=rng.choice([1, 1, 2, 3]),
            rest=rng.random() < 0.45,
            fasting=rng.random() < 0.35,
            sleep_hours=u(3.0, 9.0),
            steps_drop_days=rng.choice([0, 1, 2, 3, 4]),
            steps_interrupted=rng.random() < 0.3,
            no_steps_rest_of_active=rng.random() < 0.2,
        )
        try:
            if pred(v):
                return v
        except Exception:
            continue
    # fallback determinístico por família
    return _forced_sample(base_id, rng)


def _forced_sample(base_id: int, rng: Any) -> VitalSnapshot:
    v = VitalSnapshot(
        pas=120, pad=80, hr=72, spo2=98, temp_c=36.6, glucose_mgdl=100,
        steps_drop_pct=0, sleep_worsen_pct=0, hr_baseline_rise=0, spo2_drop_points=0,
        pas_basal=120, pad_basal=80, spo2_basal=98, temp_basal=36.6, glucose_basal=100,
        glucose_prev=100, consecutive_valid=1, rest=False, fasting=False,
    )
    # aplica um núcleo conhecido por perfil
    if 1 <= base_id <= 6:
        v.pas, v.pad, v.hr = 190, 115, 125
        v.spo2, v.temp_c, v.glucose_mgdl = 88, 38.5, 280
    elif 16 <= base_id <= 21:
        v.pas, v.hr, v.spo2, v.temp_c = 85, 125, 88, 38.5
    elif 30 <= base_id <= 36:
        v.spo2, v.hr, v.temp_c = 88, 125, 38.5
    elif 45 <= base_id <= 51:
        v.temp_c, v.hr, v.pas, v.spo2 = 39.5, 125, 95, 90
    elif 61 <= base_id <= 65:
        v.glucose_mgdl, v.hr, v.pas, v.consciousness_altered = 45, 120, 95, True
    elif 73 <= base_id <= 79:
        v.glucose_mgdl, v.temp_c, v.hr, v.pas = 420, 38.5, 125, 95
    elif 87 <= base_id <= 90:
        v.hr, v.pas, v.spo2 = 38, 95, 90
    elif 91 <= base_id <= 93:
        v.hr, v.pas, v.spo2, v.temp_c = 140, 150, 90, 38.5
    elif 103 <= base_id <= 108:
        v.steps_drop_pct, v.sleep_worsen_pct, v.hr_baseline_rise = 55, 40, 18
        v.spo2_drop_points, v.temp_c, v.pas, v.hr = 4, 38.5, 95, 120
    elif 117 <= base_id <= 130:
        v.temp_c, v.hr, v.pas, v.spo2, v.glucose_mgdl = 38.5, 135, 95, 90, 280
        v.steps_drop_pct = 45
    elif 131 <= base_id <= 144:
        v.pas, v.hr, v.hr_baseline_rise, v.steps_drop_pct = 85, 125, 22, 55
        v.glucose_mgdl, v.temp_c = 420, 39.5
        v.pas_basal = 130
    else:
        v.steps_interrupted = True
        v.no_steps_rest_of_active = True
        v.steps_drop_pct = 55
        v.pas, v.hr, v.spo2, v.glucose_mgdl = 85, 140, 88, 45
        v.pas_basal = 130
    pred = PREDICATES.get(base_id)
    if pred is not None:
        try:
            if pred(v):
                return v
        except Exception:
            pass
    return v

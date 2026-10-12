"""Gabarito R3 (Leandro, 12/10/2026): alerta principal nos 51 casos-base com conflito."""
import json
from pathlib import Path

import pytest

from src.clinical_intelligence.alert_matrix_rules import AlertMatrixEngine, VitalSnapshot

CASES = json.loads((Path(__file__).parent / "fixtures" / "r3_principal_gabarito.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("base_rule", sorted(CASES))
def test_principal_segue_gabarito_r3(base_rule):
    case = CASES[base_rule]
    res = AlertMatrixEngine().evaluate(VitalSnapshot(**case["vitals"]))
    hit_ids = [h.rule_id for h in res.hits]
    assert base_rule in hit_ids, "o alerta-base da R2 precisa continuar disparando"
    assert res.primary_rule_id == case["principal"]
    assert res.max_severity == case["gravidade"]


def test_gabarito_tem_51_casos():
    assert len(CASES) == 51

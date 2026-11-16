"""Filtro de treino: empate redundante sai, subida R3 fica, divergência sai."""

from __future__ import annotations

import pandas as pd

from src.clinical_intelligence.alert_matrix_dataset import filter_divergent_and_redundant


def _row(**overrides):
    base = {
        "pas": 0.0,
        "sampled_rule_id": "",
        "rule_id": "",
        "severity": "none",
        "is_true_alert": 0,
        "is_false_positive": 0,
    }
    base.update(overrides)
    return base


def test_filter_keeps_upgrade_and_drops_tie_divergence_conflict_and_duplicate():
    df = pd.DataFrame(
        [
            _row(pas=1, sampled_rule_id="n2u_012", rule_id="n2u_011", severity="leve", is_true_alert=1),
            _row(pas=2, sampled_rule_id="n2u_045", rule_id="n2u_097", severity="moderado", is_true_alert=1),
            _row(pas=3, sampled_rule_id="n2u_009", rule_id="n2u_020", severity="critico", is_true_alert=1),
            _row(pas=7, sampled_rule_id="n2u_001", rule_id="n2u_050", severity="critico", is_true_alert=1),
            _row(pas=4, sampled_rule_id="n2u_020", rule_id="n2u_020", severity="leve", is_true_alert=1),
            _row(pas=4, sampled_rule_id="n2u_021", rule_id="n2u_021", severity="moderado", is_true_alert=1),
            _row(pas=5, sampled_rule_id="n2u_030", rule_id="n2u_030", severity="leve", is_true_alert=1),
            _row(pas=5, sampled_rule_id="n2u_030", rule_id="n2u_030", severity="leve", is_true_alert=1),
            _row(pas=6, sampled_rule_id="n2u_008", rule_id="n2u_008", severity="moderado", is_true_alert=1),
        ]
    )
    out = filter_divergent_and_redundant(df)
    report = out.attrs["filter_report"]
    assert report["dropped_redundant_tie"] == 1
    assert report["kept_r3_upgrade"] == 1
    assert report["dropped_divergent_overlap"] == 1
    assert report["kept_unreviewed_cofire"] == 1
    assert report["dropped_conflicting_label"] == 2
    assert report["dropped_duplicate"] == 1
    assert report["rows_out"] == 4
    kept = set(zip(out["sampled_rule_id"], out["rule_id"]))
    assert kept == {
        ("n2u_045", "n2u_097"),
        ("n2u_001", "n2u_050"),
        ("n2u_030", "n2u_030"),
        ("n2u_008", "n2u_008"),
    }

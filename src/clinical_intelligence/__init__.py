"""
Motor de inteligência clínica preditiva multimodal.

Import lazy: submódulos leves (alert_ingest, rules) não puxam pipeline/torch.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ClinicalIntelligencePipeline",
    "FuzzyClinicalEngine",
    "GhostSignalDetector",
    "WearableSignalProcessor",
    "AlertMatrixEngine",
    "VitalSnapshot",
    "AlertMatrixClassifier",
    "assess_ingest_alerts",
    "merge_anomaly_with_alerts",
]

_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "ClinicalIntelligencePipeline": (
        "src.clinical_intelligence.pipeline",
        "ClinicalIntelligencePipeline",
    ),
    "FuzzyClinicalEngine": (
        "src.clinical_intelligence.fuzzy_engine",
        "FuzzyClinicalEngine",
    ),
    "GhostSignalDetector": (
        "src.clinical_intelligence.ghost_signals",
        "GhostSignalDetector",
    ),
    "WearableSignalProcessor": (
        "src.clinical_intelligence.signal_processing",
        "WearableSignalProcessor",
    ),
    "AlertMatrixEngine": (
        "src.clinical_intelligence.alert_matrix_rules",
        "AlertMatrixEngine",
    ),
    "VitalSnapshot": (
        "src.clinical_intelligence.alert_matrix_rules",
        "VitalSnapshot",
    ),
    "AlertMatrixClassifier": (
        "src.clinical_intelligence.alert_matrix_classifier",
        "AlertMatrixClassifier",
    ),
    "assess_ingest_alerts": (
        "src.clinical_intelligence.alert_ingest",
        "assess_ingest_alerts",
    ),
    "merge_anomaly_with_alerts": (
        "src.clinical_intelligence.alert_ingest",
        "merge_anomaly_with_alerts",
    ),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_ATTRS:
        import importlib

        mod_name, attr = _LAZY_ATTRS[name]
        mod = importlib.import_module(mod_name)
        value = getattr(mod, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

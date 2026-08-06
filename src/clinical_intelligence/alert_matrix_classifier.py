"""
Classificador multi-tarefa treinado na matriz de alertas.

Saídas:
  1. severity: none | leve | moderado | critico
  2. is_false_positive: probabilidade de ser FP (não alertar)
  3. is_true_alert: probabilidade de alerta verdadeiro

Pipeline de inferência combina motor de regras (explainable) + ML
para calibrar confiança e suprimir FPs.
"""

from __future__ import annotations

import json
import logging
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler

from src.clinical_intelligence.alert_matrix_dataset import FEATURE_COLUMNS, SEVERITY_LABELS
from src.clinical_intelligence.alert_matrix_rules import (
    AlertMatrixEngine,
    AlertMatrixResult,
    VitalSnapshot,
    rules_catalog,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path("data/models")


class AlertMatrixClassifier:
    """Modelo + regras para classificação de alertas e FPs."""

    def __init__(self):
        self.scaler = StandardScaler()
        self.severity_encoder = LabelEncoder()
        self.severity_clf: Optional[GradientBoostingClassifier] = None
        self.fp_clf: Optional[RandomForestClassifier] = None
        self.alert_clf: Optional[RandomForestClassifier] = None
        self.feature_columns = list(FEATURE_COLUMNS)
        self.engine = AlertMatrixEngine()
        self.metrics_: Dict[str, Any] = {}

    def fit(self, df: pd.DataFrame, test_size: float = 0.2, random_state: int = 42) -> Dict[str, Any]:
        X = df[self.feature_columns].astype(float).values
        y_sev = df["severity"].astype(str).values
        y_fp = df["is_false_positive"].astype(int).values
        y_alert = df["is_true_alert"].astype(int).values

        # Garantir todas as classes de severidade no encoder
        self.severity_encoder.fit(SEVERITY_LABELS)
        y_sev_enc = self.severity_encoder.transform(
            [s if s in SEVERITY_LABELS else "none" for s in y_sev]
        )

        X_train, X_test, ysev_tr, ysev_te, yfp_tr, yfp_te, yal_tr, yal_te = train_test_split(
            X,
            y_sev_enc,
            y_fp,
            y_alert,
            test_size=test_size,
            random_state=random_state,
            stratify=y_sev_enc,
        )

        self.scaler.fit(X_train)
        Xtr = self.scaler.transform(X_train)
        Xte = self.scaler.transform(X_test)

        self.severity_clf = GradientBoostingClassifier(
            n_estimators=120,
            max_depth=4,
            learning_rate=0.08,
            random_state=random_state,
        )
        self.severity_clf.fit(Xtr, ysev_tr)

        self.fp_clf = RandomForestClassifier(
            n_estimators=200,
            max_depth=12,
            min_samples_leaf=2,
            class_weight="balanced",
            random_state=random_state,
            n_jobs=-1,
        )
        self.fp_clf.fit(Xtr, yfp_tr)

        self.alert_clf = RandomForestClassifier(
            n_estimators=200,
            max_depth=12,
            min_samples_leaf=2,
            class_weight="balanced",
            random_state=random_state,
            n_jobs=-1,
        )
        self.alert_clf.fit(Xtr, yal_tr)

        metrics = self._evaluate(Xte, ysev_te, yfp_te, yal_te)
        self.metrics_ = metrics
        logger.info("Treino concluído: %s", json.dumps(metrics, indent=2, default=str))
        return metrics

    def _evaluate(self, Xte, ysev_te, yfp_te, yal_te) -> Dict[str, Any]:
        assert self.severity_clf and self.fp_clf and self.alert_clf
        sev_pred = self.severity_clf.predict(Xte)
        fp_pred = self.fp_clf.predict(Xte)
        al_pred = self.alert_clf.predict(Xte)

        sev_names = list(self.severity_encoder.classes_)
        # Mapear indices para nomes
        sev_true_names = [sev_names[i] for i in ysev_te]
        sev_pred_names = [sev_names[i] for i in sev_pred]

        p_fp, r_fp, f_fp, _ = precision_recall_fscore_support(
            yfp_te, fp_pred, average="binary", zero_division=0
        )
        p_al, r_al, f_al, _ = precision_recall_fscore_support(
            yal_te, al_pred, average="binary", zero_division=0
        )

        # FP detection: queremos alta precision e recall em is_false_positive=1
        cm_fp = confusion_matrix(yfp_te, fp_pred, labels=[0, 1]).tolist()
        cm_sev = confusion_matrix(
            ysev_te, sev_pred, labels=list(range(len(sev_names)))
        ).tolist()

        return {
            "n_test": int(len(ysev_te)),
            "severity_f1_macro": float(
                f1_score(ysev_te, sev_pred, average="macro", zero_division=0)
            ),
            "severity_f1_weighted": float(
                f1_score(ysev_te, sev_pred, average="weighted", zero_division=0)
            ),
            "severity_report": classification_report(
                sev_true_names, sev_pred_names, zero_division=0, output_dict=True
            ),
            "severity_confusion": cm_sev,
            "severity_labels": sev_names,
            "false_positive_precision": float(p_fp),
            "false_positive_recall": float(r_fp),
            "false_positive_f1": float(f_fp),
            "false_positive_confusion": cm_fp,
            "true_alert_precision": float(p_al),
            "true_alert_recall": float(r_al),
            "true_alert_f1": float(f_al),
        }

    def predict_features(self, features: Dict[str, float]) -> Dict[str, Any]:
        assert self.severity_clf and self.fp_clf and self.alert_clf
        x = np.array([[float(features.get(c, 0.0)) for c in self.feature_columns]])
        xs = self.scaler.transform(x)
        sev_i = int(self.severity_clf.predict(xs)[0])
        sev = self.severity_encoder.inverse_transform([sev_i])[0]
        fp_prob = float(self.fp_clf.predict_proba(xs)[0][1])
        alert_prob = float(self.alert_clf.predict_proba(xs)[0][1])
        sev_proba = {
            self.severity_encoder.inverse_transform([i])[0]: float(p)
            for i, p in enumerate(self.severity_clf.predict_proba(xs)[0])
        }
        return {
            "ml_severity": sev,
            "ml_severity_proba": sev_proba,
            "ml_false_positive_prob": fp_prob,
            "ml_true_alert_prob": alert_prob,
        }

    def assess(
        self,
        vitals: VitalSnapshot,
        fp_suppress_threshold: float = 0.55,
        alert_threshold: float = 0.80,
    ) -> Dict[str, Any]:
        """
        Inferência combinada regras + ML.

        - Regras definem hits e severidade ground-truth operacional
        - ML estima FP e confidência; se FP alto e regra não bate → suppress
        - Se regra bate → true alert (nome da matriz)
        - Sem regra: prioridade absoluta é suprimir falso positivo
        """
        rule_result: AlertMatrixResult = self.engine.evaluate(vitals)
        feats = vitals.to_feature_dict()
        ml = self.predict_features(feats) if self.severity_clf else {
            "ml_severity": "none",
            "ml_severity_proba": {},
            "ml_false_positive_prob": 0.0,
            "ml_true_alert_prob": 0.0,
        }

        suppressed = False
        final_severity = rule_result.max_severity
        final_alert = rule_result.is_true_alert
        decision = "rule_match" if rule_result.is_true_alert else "no_rule"

        if rule_result.is_true_alert:
            confidence = max(
                0.55,
                0.55 * ml["ml_true_alert_prob"]
                + 0.45 * (1.0 - ml["ml_false_positive_prob"]),
            )
            if ml["ml_false_positive_prob"] > 0.85 and ml["ml_true_alert_prob"] < 0.25:
                confidence *= 0.7
                decision = "rule_match_low_ml_confidence"
        else:
            if ml["ml_false_positive_prob"] >= fp_suppress_threshold:
                suppressed = True
                final_severity = "none"
                final_alert = False
                decision = "suppressed_false_positive"
                confidence = max(
                    ml["ml_false_positive_prob"], 1.0 - ml["ml_true_alert_prob"]
                )
            elif (
                ml["ml_true_alert_prob"] >= max(alert_threshold, 0.80)
                and ml["ml_false_positive_prob"] < 0.25
                and ml["ml_severity"] in ("leve", "moderado", "critico")
            ):
                final_severity = ml["ml_severity"]
                if final_severity == "critico":
                    final_severity = "moderado"
                final_alert = True
                decision = "ml_soft_alert_no_rule"
                confidence = ml["ml_true_alert_prob"] * 0.5
            else:
                suppressed = (
                    ml["ml_false_positive_prob"] >= 0.35
                    or rule_result.is_false_positive_candidate
                )
                final_severity = "none"
                final_alert = False
                decision = (
                    "suppressed_false_positive" if suppressed else "stable_or_noise"
                )
                confidence = max(
                    1.0 - ml["ml_true_alert_prob"],
                    ml["ml_false_positive_prob"],
                    0.6,
                )

        return {
            "is_true_alert": final_alert,
            "is_false_positive": suppressed
            or (
                not rule_result.is_true_alert
                and ml["ml_false_positive_prob"] >= fp_suppress_threshold
            )
            or (
                not rule_result.is_true_alert
                and not final_alert
                and rule_result.is_false_positive_candidate
            ),
            "severity": final_severity,
            "confidence": float(confidence),
            "decision": decision,
            "primary_alert_name": rule_result.primary_alert_name,
            "primary_rule_id": rule_result.primary_rule_id,
            "rule_hits": [h.to_dict() for h in rule_result.hits],
            "rule_explanation": rule_result.explanation,
            "ml": ml,
            "vitals": feats,
        }

    def save(self, model_dir: Path | str = DEFAULT_MODEL_DIR) -> Path:
        out = Path(model_dir)
        out.mkdir(parents=True, exist_ok=True)
        payload = {
            "scaler": self.scaler,
            "severity_encoder": self.severity_encoder,
            "severity_clf": self.severity_clf,
            "fp_clf": self.fp_clf,
            "alert_clf": self.alert_clf,
            "feature_columns": self.feature_columns,
            "metrics": self.metrics_,
            "rules_catalog": rules_catalog(),
        }
        path = out / "alert_matrix_classifier.pkl"
        with open(path, "wb") as f:
            pickle.dump(payload, f)
        meta = {
            "model": "alert_matrix_classifier",
            "features": self.feature_columns,
            "severity_labels": SEVERITY_LABELS,
            "n_rules": len(rules_catalog()),
            "metrics": self.metrics_,
        }
        with open(out / "alert_matrix_classifier_meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False, default=str)
        with open(out / "alert_matrix_rules.json", "w", encoding="utf-8") as f:
            json.dump(rules_catalog(), f, indent=2, ensure_ascii=False)
        return path

    @classmethod
    def load(cls, model_dir: Path | str = DEFAULT_MODEL_DIR) -> "AlertMatrixClassifier":
        path = Path(model_dir) / "alert_matrix_classifier.pkl"
        with open(path, "rb") as f:
            payload = pickle.load(f)
        obj = cls()
        obj.scaler = payload["scaler"]
        obj.severity_encoder = payload["severity_encoder"]
        obj.severity_clf = payload["severity_clf"]
        obj.fp_clf = payload["fp_clf"]
        obj.alert_clf = payload["alert_clf"]
        obj.feature_columns = payload["feature_columns"]
        obj.metrics_ = payload.get("metrics", {})
        return obj

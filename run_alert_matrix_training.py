#!/usr/bin/env python3
"""
Treina classificador de alertas clínicos + falsos positivos a partir da
matriz de cruzamentos (PA, SpO2, temp, glicemia, FC, passos/sono).

Uso:
  python run_alert_matrix_training.py
  python run_alert_matrix_training.py --n-per-rule 100 --n-fp 3000
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.clinical_intelligence.alert_matrix_classifier import AlertMatrixClassifier
from src.clinical_intelligence.alert_matrix_dataset import generate_dataset
from src.clinical_intelligence.alert_matrix_rules import (
    AlertMatrixEngine,
    VitalSnapshot,
    rules_catalog,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("alert_matrix_training")


def main() -> int:
    parser = argparse.ArgumentParser(description="Treino matriz de alertas clínicos")
    parser.add_argument("--n-per-rule", type=int, default=100)
    parser.add_argument("--n-normal", type=int, default=2000)
    parser.add_argument("--n-fp", type=int, default=2500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model-dir", default="data/models")
    parser.add_argument(
        "--dataset-out",
        default="data/clinical_intelligence/alert_matrix_training.csv",
    )
    args = parser.parse_args()

    catalog = rules_catalog()
    logger.info("Regras na matriz: %d", len(catalog))

    logger.info(
        "Gerando dataset (n_per_rule=%d, normal=%d, fp=%d)…",
        args.n_per_rule,
        args.n_normal,
        args.n_fp,
    )
    df = generate_dataset(
        n_per_rule=args.n_per_rule,
        n_normal=args.n_normal,
        n_false_positive=args.n_fp,
        seed=args.seed,
    )
    out_csv = Path(args.dataset_out)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    logger.info(
        "Dataset: %d linhas | true_alert=%d | fp=%d | severity=%s",
        len(df),
        int(df["is_true_alert"].sum()),
        int(df["is_false_positive"].sum()),
        df["severity"].value_counts().to_dict(),
    )

    clf = AlertMatrixClassifier()
    metrics = clf.fit(df)
    model_path = clf.save(args.model_dir)
    logger.info("Modelo salvo: %s", model_path)

    # Smoke de casos clínicos
    engine = AlertMatrixEngine()
    demos = [
        ("crise_hta_taqui", VitalSnapshot(pas=190, pad=115, hr=120, spo2=97, temp_c=36.8, glucose_mgdl=110)),
        ("hipoxemia", VitalSnapshot(pas=120, pad=80, hr=85, spo2=88, temp_c=36.6, glucose_mgdl=100)),
        ("fp_borderline_hr", VitalSnapshot(pas=118, pad=76, hr=105, spo2=98, temp_c=36.7, glucose_mgdl=105)),
        ("normal", VitalSnapshot(pas=118, pad=76, hr=72, spo2=98, temp_c=36.6, glucose_mgdl=100)),
        ("hipo_grave", VitalSnapshot(pas=95, pad=60, hr=120, spo2=97, temp_c=36.5, glucose_mgdl=45, consciousness_altered=True)),
    ]
    print("\n=== Smoke assess (regras + ML) ===")
    for name, vitals in demos:
        res = clf.assess(vitals)
        print(
            f"{name:20s} severity={res['severity']:10s} "
            f"alert={res['is_true_alert']} fp={res['is_false_positive']} "
            f"decision={res['decision']}"
        )
        if res.get("primary_alert_name"):
            print(f"  → {res['primary_alert_name']}")

    summary = {
        "n_rules": len(catalog),
        "n_samples": len(df),
        "metrics": {
            "severity_f1_macro": metrics["severity_f1_macro"],
            "false_positive_precision": metrics["false_positive_precision"],
            "false_positive_recall": metrics["false_positive_recall"],
            "false_positive_f1": metrics["false_positive_f1"],
            "true_alert_precision": metrics["true_alert_precision"],
            "true_alert_recall": metrics["true_alert_recall"],
            "true_alert_f1": metrics["true_alert_f1"],
        },
        "model_path": str(model_path),
        "dataset": str(out_csv),
    }
    summary_path = Path(args.model_dir) / "alert_matrix_training_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print("\n=== Resumo treino ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

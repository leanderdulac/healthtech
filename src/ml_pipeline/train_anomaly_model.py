"""
Script de treinamento para Vertex AI CustomTrainingJob.
Lê features exportadas do datalake e treina Isolation Forest.
"""
import argparse
import json
import os
import pickle
from pathlib import Path

import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

FEATURE_COLUMNS = [
    "avg_resting_hr", "max_hr", "min_hr", "avg_spo2", "avg_hrv",
    "total_steps", "sleep_hours", "stress_peak", "anomaly_episodes",
    "coverage_24h", "total_alerts",
]


def train(data_path: str, model_dir: str) -> None:
    df = pd.read_csv(data_path)
    X = df[FEATURE_COLUMNS].fillna(0).values

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(n_estimators=100, contamination=0.1, random_state=42)
    model.fit(X_scaled)

    out = Path(model_dir)
    out.mkdir(parents=True, exist_ok=True)

    with open(out / "model.pkl", "wb") as f:
        pickle.dump({"model": model, "scaler": scaler, "features": FEATURE_COLUMNS}, f)

    metrics = {"samples": len(df), "features": len(FEATURE_COLUMNS)}
    with open(out / "metrics.json", "w") as f:
        json.dump(metrics, f)

    print(f"Modelo salvo em {out / 'model.pkl'} ({len(df)} amostras)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", default=os.getenv("AIP_TRAINING_DATA_URI", "training_data.csv"))
    parser.add_argument("--model-dir", default=os.getenv("AIP_MODEL_DIR", "/tmp/model"))
    args = parser.parse_args()
    train(args.data_path, args.model_dir)
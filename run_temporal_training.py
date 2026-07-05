#!/usr/bin/env python3
"""
Treinamento do modelo temporal TCN+LSTM com features ghost + fuzzy.

Pipeline:
  1. Gera telemetria via Datalake (ou usa existente)
  2. Extrai sequências temporais com ghost/fuzzy por timestep
  3. Treina TCN+BiLSTM multi-horizonte (6h, 24h, 72h)
  4. Salva modelo em data/models/temporal_tcn_lstm.pt
"""

import argparse
import logging
from datetime import datetime
from pathlib import Path

from src.clinical_intelligence.temporal_features import TEMPORAL_FEATURE_COLUMNS
from src.clinical_intelligence.temporal_model import TemporalModelWrapper, TORCH_AVAILABLE
from src.datalake.config import LakehouseConfig
from src.datalake.pipeline.orchestrator import DatalakeOrchestrator
from src.datalake.utils.telemetry_simulator import SimulationConfig
from src.clinical_intelligence.temporal_features import TemporalFeatureBuilder

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Treino TCN+LSTM ghost+fuzzy")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--seq-len", type=int, default=32)
    parser.add_argument("--patients", type=int, default=5)
    parser.add_argument("--hours", type=float, default=80.0,
                        help="Horas de telemetria (mín. ~80h para horizonte 72h + seq_len)")
    parser.add_argument("--subsample", type=int, default=30,
                        help="Subsample vitals (30 ≈ 5min/step com HR 10s)")
    parser.add_argument("--skip-pipeline", action="store_true", help="Usar datalake existente")
    args = parser.parse_args()

    print_section("TREINO TEMPORAL TCN+LSTM — GHOST + FUZZY")
    print(f"  PyTorch disponível : {'Sim' if TORCH_AVAILABLE else 'Não (fallback sklearn)'}")
    print(f"  Features/timestep  : {len(TEMPORAL_FEATURE_COLUMNS)}")
    print(f"  Arquitetura        : TCN (dilatação 1,2,4) → BiLSTM → 3 heads")

    lakehouse_config = LakehouseConfig(base_path=Path("data/lakehouse"))
    orchestrator = DatalakeOrchestrator(lakehouse_config)

    partition_dates = None
    profiles = []

    if not args.skip_pipeline:
        print_section("FASE 1: GERAÇÃO DE TELEMETRIA")
        sim_config = SimulationConfig(
            num_patients=args.patients,
            hours=args.hours,
            hr_interval_seconds=10,
            anomaly_probability=0.08,
            seed=42,
        )
        start_time = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = orchestrator.run_full_pipeline(
            simulation_config=sim_config,
            start_time=start_time,
        )
        partition_dates = result.partition_dates
        profiles = result.patient_profiles
        print(f"  Bronze eventos : {result.ingestion.get('total', 0)}")
        print(f"  Pacientes      : {len(profiles)}")
    else:
        from src.datalake.utils.telemetry_simulator import TelemetrySimulator
        sim = TelemetrySimulator(SimulationConfig(num_patients=args.patients, hours=args.hours))
        profiles = sim.patient_profiles

    print_section("FASE 2: EXTRAÇÃO DE SEQUÊNCIAS GHOST+FUZZY")
    builder = TemporalFeatureBuilder(
        seq_len=args.seq_len,
        subsample=args.subsample,
        feature_stride=4,
        exclusive_horizons=True,
    )
    print(f"  Resolução temporal : {builder.minutes_per_step:.1f} min/passo")
    for name, desc in builder.horizon_summary().items():
        print(f"  {name}: {desc}")
    X, y, patient_ids = builder.build_from_datalake(
        query_engine=orchestrator.query_engine,
        patient_profiles=profiles,
        partition_dates=partition_dates,
    )

    if len(X) == 0:
        print("\n  ERRO: Nenhuma sequência gerada. Execute sem --skip-pipeline.")
        return

    print(f"  Sequências     : {len(X)}")
    print(f"  Shape X        : {X.shape}")
    print(f"  Shape y        : {y.shape}")
    print(f"  Taxa positiva 6h  : {y[:, 0].mean():.1%}")
    print(f"  Taxa positiva 24h : {y[:, 1].mean():.1%}")
    print(f"  Taxa positiva 72h : {y[:, 2].mean():.1%}")

    print_section("FASE 3: TREINAMENTO TCN+BiLSTM")
    model = TemporalModelWrapper(model_dir=Path("data/models"))
    train_result = model.train(X, y, epochs=args.epochs, batch_size=32, learning_rate=1e-3)

    print(f"\n  Status         : {train_result.get('status')}")
    print(f"  Amostras       : {train_result.get('samples', 0)}")
    print(f"  Épocas         : {train_result.get('epochs_run', 0)}")
    print(f"  Modelo         : {train_result.get('model_path', 'N/A')}")

    metrics = train_result.get("metrics", {})
    if metrics:
        print(f"\n  Métricas por horizonte:")
        for horizon, m in metrics.items():
            if "precision" in m:
                print(f"    {horizon}: P={m['precision']:.2f} R={m['recall']:.2f} F1={m['f1']:.2f} "
                      f"(pos_rate={m.get('positive_rate', 0):.1%})")
            else:
                print(f"    {horizon}: accuracy={m.get('accuracy', 0):.2f} f1={m.get('f1', 0):.2f}")

    print_section("FASE 4: INFERÊNCIA DE VALIDAÇÃO")
    sample_pred = model.predict_single(X[-1])
    print(f"  Última sequência:")
    print(f"    P(6h)  = {sample_pred['prob_6h']:.1%}")
    print(f"    P(24h) = {sample_pred['prob_24h']:.1%}")
    print(f"    P(72h) = {sample_pred['prob_72h']:.1%}")
    print(f"    Horizonte em risco: {sample_pred['horizon_at_risk']}")

    print_section("TREINO CONCLUÍDO")
    print("  Modelo salvo em: data/models/temporal_tcn_lstm.pt")
    print("  Features: wearable + derived + ghost(8) + fuzzy(4)")


if __name__ == "__main__":
    main()
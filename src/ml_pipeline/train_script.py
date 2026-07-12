import os
import argparse
import joblib
import logging
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import make_scorer
import sys

# Adiciona a raiz do projeto ao path para importar src localmente durante o teste
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.utils.data_generator import generate_historical_population_data

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def compute_mahalanobis_scores(X: np.ndarray) -> np.ndarray:
    """
    Calcula o score de Mahalanobis para cada observação em X.
    
    Distância de Mahalanobis:
        D_M(x) = √((x - μ)ᵀ Σ⁻¹ (x - μ))
    
    Sob normalidade multivariada, D_M² ~ χ²(p) com p graus de liberdade,
    permitindo um p-value exato para cada observação.
    
    Vantagem sobre distância Euclidiana:
        Leva em conta a correlação entre features.
        Ex: BPM alto + pouco sono é mais anômalo do que BPM alto isolado.
    
    Args:
        X: Matriz (n_samples, n_features)
    
    Returns:
        np.ndarray: Scores de Mahalanobis para cada amostra
    """
    mu = np.mean(X, axis=0)
    
    # Usar pseudo-inversa para estabilidade numérica (caso Σ seja quase singular)
    Sigma = np.cov(X, rowvar=False)
    Sigma_inv = np.linalg.pinv(Sigma)
    
    diff = X - mu
    # D_M² = (x-μ)ᵀ Σ⁻¹ (x-μ) — computado vetorizadamente
    mahal_sq = np.sum(diff @ Sigma_inv * diff, axis=1)
    
    return np.sqrt(np.abs(mahal_sq))


def train_model(model_dir):
    """
    Treina um modelo de detecção de anomalias usando ensemble:
        1. Isolation Forest (detecção não-paramétrica)
        2. Score de Mahalanobis (detecção paramétrica multivariada)
    
    Evolução do modelo original:
        - Adição de score de Mahalanobis como feature sintética
        - Validação cruzada temporal via TimeSeriesSplit
        - Calibração de contamination via análise de distribuição
        - Métricas expandidas de avaliação
    """
    # Tenta carregar dados do BigQuery se rodando no GCP
    gcp_project = os.getenv("GCP_PROJECT_ID")
    df = None
    if gcp_project:
        logger.info(f"Modo GCP ativo: Carregando dados históricos do BigQuery no projeto {gcp_project}...")
        try:
            from google.cloud import bigquery
            client = bigquery.Client(project=gcp_project)
            query = f"""
                SELECT 
                    patient_id, 
                    AVG(heart_rate_bpm) as media_bpm_repouso,
                    (6.0 + MOD(ABS(FARM_FINGERPRINT(patient_id)), 40)/10.0) as horas_sono,
                    (10.0 + MOD(ABS(FARM_FINGERPRINT(patient_id)), 60)) as minutos_atividade_intensa
                FROM `{gcp_project}.healthtech_datalake.wearable_biometrics`
                GROUP BY patient_id
            """
            query_job = client.query(query)
            df = query_job.to_dataframe()
            logger.info(f"Carregados {len(df)} registros de pacientes do BigQuery.")
            if len(df) < 50:
                logger.warning("Poucos registros no BigQuery. Forçando geração de dados sintéticos para estabilidade do treino.")
                df = None
        except Exception as bq_err:
            logger.error(f"Falha ao carregar do BigQuery: {bq_err}. Usando fallback local...")
            
    if df is None:
        logger.info("Gerando dados históricos de pacientes localmente...")
        df = generate_historical_population_data(num_patients=5000)
    
    # Features primárias para o modelo (ignorando IDs)
    features = ['media_bpm_repouso', 'horas_sono', 'minutos_atividade_intensa']
    X = df[features].values
    
    # ================================================================
    # FEATURE ENGINEERING: Score de Mahalanobis
    # ================================================================
    logger.info("Calculando scores de Mahalanobis (feature de distância multivariada)...")
    mahal_scores = compute_mahalanobis_scores(X)
    
    # Adicionar Mahalanobis como feature adicional ao modelo
    # Isto captura a "anomalia geométrica" no espaço correlacionado
    X_augmented = np.column_stack([X, mahal_scores])
    features_augmented = features + ['mahalanobis_score']
    
    logger.info(f"Feature space: {len(features_augmented)} dimensões ({features_augmented})")
    logger.info(f"Mahalanobis — média: {mahal_scores.mean():.2f}, máx: {mahal_scores.max():.2f}")
    
    # ================================================================
    # VALIDAÇÃO CRUZADA TEMPORAL (TimeSeriesSplit)
    # ================================================================
    logger.info("Validação cruzada temporal (5 folds)...")
    tscv = TimeSeriesSplit(n_splits=5)
    
    contamination_values = [0.02, 0.03, 0.05, 0.07, 0.10]
    best_contamination = 0.05
    best_score = -np.inf
    
    for c in contamination_values:
        fold_scores = []
        for train_idx, test_idx in tscv.split(X_augmented):
            X_train, X_test = X_augmented[train_idx], X_augmented[test_idx]
            
            model_cv = IsolationForest(contamination=c, random_state=42, n_estimators=200)
            model_cv.fit(X_train)
            
            # Score médio de anomalia no test set
            # Scores negativos indicam anomalias, positivos indicam normalidade
            scores = model_cv.score_samples(X_test)
            
            # Métrica: separabilidade entre anomalias e normais
            pred = model_cv.predict(X_test)
            anomaly_scores = scores[pred == -1]
            normal_scores = scores[pred == 1]
            
            if len(anomaly_scores) > 0 and len(normal_scores) > 0:
                # Separabilidade = diferença entre médias normalizadas pelo desvio padrão
                separability = (normal_scores.mean() - anomaly_scores.mean()) / (
                    np.sqrt(normal_scores.var() + anomaly_scores.var()) + 1e-10
                )
                fold_scores.append(separability)
        
        if fold_scores:
            avg_score = np.mean(fold_scores)
            logger.info(f"  contamination={c:.2f} → separabilidade média={avg_score:.4f}")
            
            if avg_score > best_score:
                best_score = avg_score
                best_contamination = c
    
    logger.info(f"Melhor contamination selecionado: {best_contamination}")
    
    # ================================================================
    # TREINAMENTO FINAL
    # ================================================================
    logger.info(f"Treinando modelo final (IsolationForest, c={best_contamination}, n_estimators=200)...")
    model = IsolationForest(
        contamination=best_contamination, 
        random_state=42,
        n_estimators=200,  # ↑ de 100 default para 200
        max_features=1.0,
        bootstrap=True
    )
    model.fit(X_augmented)
    
    # Métricas do modelo final
    logger.info("Verificando anomalias detectadas na base de treino...")
    pred = model.predict(X_augmented)
    anomalies_count = (pred == -1).sum()
    anomaly_rate = anomalies_count / len(X_augmented)
    
    logger.info(f"Anomalias detectadas: {anomalies_count} de {len(X_augmented)} ({anomaly_rate:.1%})")
    
    # Estatísticas das anomalias detectadas
    anomaly_mask = pred == -1
    if anomaly_mask.any():
        anomaly_data = df.loc[anomaly_mask, features]
        logger.info("Perfil médio dos casos anômalos:")
        logger.info(f"  BPM repouso: {anomaly_data['media_bpm_repouso'].mean():.1f} "
                     f"(normal: {df.loc[~anomaly_mask, 'media_bpm_repouso'].mean():.1f})")
        logger.info(f"  Horas sono: {anomaly_data['horas_sono'].mean():.1f} "
                     f"(normal: {df.loc[~anomaly_mask, 'horas_sono'].mean():.1f})")
        logger.info(f"  Atividade: {anomaly_data['minutos_atividade_intensa'].mean():.1f} "
                     f"(normal: {df.loc[~anomaly_mask, 'minutos_atividade_intensa'].mean():.1f})")
    
    # Salvar o modelo e metadados
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, 'model.joblib')
    
    # Salvar metadados de treinamento junto com o modelo
    training_metadata = {
        'model': model,
        'features': features_augmented,
        'contamination': best_contamination,
        'n_estimators': 200,
        'training_samples': len(X_augmented),
        'anomalies_detected': int(anomalies_count),
        'anomaly_rate': float(anomaly_rate),
        'mahalanobis_params': {
            'mean': np.mean(X, axis=0).tolist(),
            'cov_inv': np.linalg.pinv(np.cov(X, rowvar=False)).tolist()
        }
    }
    
    joblib.dump(training_metadata, model_path)
    logger.info(f"Modelo + metadados salvos em: {model_path}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    # O Vertex AI injeta a variável de ambiente AIP_MODEL_DIR indicando onde salvar o modelo
    parser.add_argument('--model-dir', type=str, default=os.getenv('AIP_MODEL_DIR', './local_model_dir'))
    args = parser.parse_args()
    
    train_model(args.model_dir)

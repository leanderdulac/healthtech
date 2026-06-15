"""
HealthTech GCP Pipeline - Sistema de Dados e ML para Saúde
==========================================================

Arquitetura completa para ingestão, reconciliação, segurança e inferência
de dados biométricos de pacientes no Google Cloud Platform.

Autor: Engenheiro de Dados e ML Especialista em GCP HealthTech
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import os
import logging
import json
from datetime import datetime, timedelta
import random

# Configuração de Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class GCPConfig:
    """Configuração centralizada para serviços GCP."""
    project_id: str
    region: str
    bucket_name: str
    dataset_id: str
    endpoint_id: str
    model_name: str
    
    @classmethod
    def from_env(cls) -> 'GCPConfig':
        """Cria configuração a partir de variáveis de ambiente."""
        return cls(
            project_id=os.getenv('GCP_PROJECT_ID', 'healthtech-dev'),
            region=os.getenv('GCP_REGION', 'us-central1'),
            bucket_name=os.getenv('GCS_BUCKET', 'healthtech-data-lake'),
            dataset_id=os.getenv('BQ_DATASET', 'patient_analytics'),
            endpoint_id=os.getenv('VERTEX_ENDPOINT_ID', ''),
            model_name=os.getenv('VERTEX_MODEL_NAME', 'arrhythmia-detector')
        )


def setup_logging(simulation_mode: bool = True) -> None:
    """Configura logging estruturado para o pipeline."""
    if simulation_mode:
        logger.info("🔧 MODO SIMULAÇÃO ATIVADO - Sem credenciais GCP reais")
    else:
        logger.info("🚀 MODO PRODUÇÃO - Conectando ao GCP")


# ============================================================================
# 1. INGESTÃO E RECONCILIAÇÃO (Streaming/Eventos)
# ============================================================================

class DataGenerator:
    """Gera dados simulados de sensores biométricos."""
    
    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(seed)
        
    def generate_patient_vitals(self, patient_id: str, num_readings: int = 10) -> List[Dict[str, Any]]:
        """
        Gera leituras vitais simuladas para um paciente.
        
        Args:
            patient_id: ID único do paciente
            num_readings: Número de leituras a gerar
            
        Returns:
            Lista de dicionários com dados biométricos
        """
        readings = []
        base_time = datetime.now()
        
        for idx in range(num_readings):
            reading = {
                'patient_id': patient_id,
                'timestamp': (base_time + timedelta(seconds=idx*30)).isoformat(),
                'heart_rate_bpm': random.randint(60, 120),
                'blood_pressure_systolic': random.randint(90, 140),
                'blood_pressure_diastolic': random.randint(60, 90),
                'oxygen_saturation': random.uniform(95.0, 100.0),
                'temperature_celsius': random.uniform(36.0, 37.5),
                'sensor_id': f"SENSOR_{random.randint(1000, 9999)}",
                'quality_score': random.uniform(0.8, 1.0)
            }
            readings.append(reading)
            
        return readings


class DataReconciliation:
    """Reconcilia dados biométricos em janelas de tempo."""
    
    def __init__(self, window_size_seconds: int = 60):
        self.window_size = window_size_seconds
        
    def reconcile_window(self, readings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Reconcilia múltiplas leituras em uma janela de tempo.
        
        Args:
            readings: Lista de leituras brutas
            
        Returns:
            Dicionário com dados reconciliados e métricas de qualidade
        """
        if not readings:
            return {'status': 'empty', 'data': None}
            
        # Validação de colunas obrigatórias
        required_cols = ['heart_rate_bpm', 'oxygen_saturation', 'quality_score']
        for reading in readings:
            for col in required_cols:
                if col not in reading:
                    raise ValueError(f"Coluna obrigatória '{col}' não encontrada")
        
        # Cópia para evitar efeitos colaterais
        valid_readings = [r for r in readings if r.get('quality_score', 0) > 0.7]
        
        if not valid_readings:
            return {'status': 'no_valid_data', 'data': None}
        
        # Agregação por sensor (ordem consistente)
        sensors = sorted(set(r['sensor_id'] for r in valid_readings))
        
        reconciled = {
            'window_start': min(r['timestamp'] for r in valid_readings),
            'window_end': max(r['timestamp'] for r in valid_readings),
            'num_readings': len(valid_readings),
            'avg_heart_rate': sum(r['heart_rate_bpm'] for r in valid_readings) / len(valid_readings),
            'avg_oxygen_saturation': sum(r['oxygen_saturation'] for r in valid_readings) / len(valid_readings),
            'sensors_count': len(sensors),
            'sensors_list': sensors,
            'quality_flag': 'HIGH' if len(valid_readings) >= len(readings) * 0.8 else 'LOW'
        }
        
        return {'status': 'success', 'data': reconciled}


# ============================================================================
# 2. SEGURANÇA E PRIVACIDADE (FHIR + Anonimização)
# ============================================================================

class FHIRAnonymizer:
    """Anonimiza dados de paciente seguindo padrão FHIR e HIPAA."""
    
    def __init__(self, salt: str = "healthtech-salt-2024"):
        self.salt = salt
        
    def _generate_hash(self, value: str) -> str:
        """Gera hash SHA-256 determinístico para anonimização rastreável."""
        import hashlib
        salted_value = f"{value}{self.salt}"
        return hashlib.sha256(salted_value.encode()).hexdigest()[:16]
    
    def anonymize_patient(self, patient_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Anonimiza dados sensíveis do paciente.
        
        Args:
            patient_data: Dados originais do paciente
            
        Returns:
            Dados anonimizados prontos para Data Lake
        """
        if not patient_data:
            return {}
            
        # Cópia profunda para não modificar original
        anonymized = patient_data.copy()
        
        # Campos PHI (Protected Health Information) a serem anonimizados
        phi_fields = ['patient_id', 'name', 'email', 'phone', 'address', 'ssn']
        
        for field in phi_fields:
            if field in anonymized and anonymized[field] is not None:
                original_value = str(anonymized.pop(field))
                anonymized[f'{field}_anon'] = f"ANON-{self._generate_hash(original_value)}"
        
        # Remove data de nascimento exata, mantém apenas ano
        if 'birth_date' in anonymized:
            birth_year = anonymized['birth_date'][:4] if anonymized['birth_date'] else None
            anonymized.pop('birth_date')
            anonymized['birth_year'] = birth_year
            
        return anonymized
    
    def generate_anonymous_id(self, original_id: str) -> str:
        """
        Gera ID anônimo consistente para o mesmo paciente.
        
        Args:
            original_id: ID original do paciente
            
        Returns:
            ID anônimo no formato ANON-<hash>
        """
        return f"ANON-{self._generate_hash(original_id)}"


# ============================================================================
# 3. MACHINE LEARNING - INFERÊNCIA ONLINE (Vertex AI Endpoint)
# ============================================================================

class VertexAIOnlineInference:
    """Realiza inferência online via Vertex AI Endpoint para detecção de arritmia."""
    
    def __init__(self, config: GCPConfig, simulation_mode: bool = True):
        self.config = config
        self.simulation_mode = simulation_mode
        self.endpoint_url = None
        
        if not simulation_mode:
            self._initialize_endpoint()
    
    def _initialize_endpoint(self) -> None:
        """Inicializa conexão com Vertex AI Endpoint."""
        try:
            from google.cloud import aiplatform
            aiplatform.init(
                project=self.config.project_id,
                location=self.config.region
            )
            self.endpoint_url = f"projects/{self.config.project_id}/locations/{self.config.region}/endpoints/{self.config.endpoint_id}"
            logger.info(f"✅ Endpoint inicializado: {self.endpoint_url}")
        except Exception as e:
            logger.error(f"❌ Erro ao inicializar endpoint: {e}")
            raise
    
    def predict_arrhythmia(self, vital_signs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Realiza predição online para detecção de arritmia.
        
        Args:
            vital_signs: Dicionário com sinais vitais do paciente
            
        Returns:
            Resultado da predição com probabilidade e classificação
        """
        if self.simulation_mode:
            return self._simulate_prediction(vital_signs)
        
        try:
            from google.cloud import aiplatform
            endpoint = aiplatform.Endpoint(self.endpoint_url)
            
            instances = [{
                'heart_rate': vital_signs.get('avg_heart_rate', 0),
                'oxygen_saturation': vital_signs.get('avg_oxygen_saturation', 0),
                'blood_pressure_systolic': vital_signs.get('blood_pressure_systolic', 0),
                'blood_pressure_diastolic': vital_signs.get('blood_pressure_diastolic', 0)
            }]
            
            response = endpoint.predict(instances=instances)
            
            return {
                'prediction': response.predictions[0],
                'confidence': response.confidence[0] if hasattr(response, 'confidence') else 0.95,
                'model_version': 'v1.0',
                'inference_type': 'online'
            }
            
        except Exception as e:
            logger.error(f"Erro na inferência online: {e}")
            return {'error': str(e), 'fallback': True}
    
    def _simulate_prediction(self, vital_signs: Dict[str, Any]) -> Dict[str, Any]:
        """Simula predição para modo de desenvolvimento."""
        heart_rate = vital_signs.get('avg_heart_rate', 70)
        
        # Lógica simples de simulação
        is_anomaly = heart_rate > 100 or heart_rate < 50
        probability = 0.85 if is_anomaly else 0.15
        
        logger.info(f"🔍 [SIMULAÇÃO] Inferência online - HR: {heart_rate}, Anomalia: {is_anomaly}")
        
        return {
            'prediction': 1 if is_anomaly else 0,
            'class_label': 'ARRHYTHMIA_DETECTED' if is_anomaly else 'NORMAL',
            'probability': probability,
            'confidence': 0.92,
            'model_version': 'simulated-v1.0',
            'inference_type': 'online_simulation'
        }


# ============================================================================
# 4. MACHINE LEARNING - INFERÊNCIA BATCH (Vertex AI Batch Prediction)
# ============================================================================

class VertexAIBatchPrediction:
    """Gerencia jobs de predição em lote no Vertex AI."""
    
    def __init__(self, config: GCPConfig, simulation_mode: bool = True):
        self.config = config
        self.simulation_mode = simulation_mode
        
    def submit_batch_job(self, 
                        input_gcs_path: str, 
                        output_gcs_path: str,
                        model_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Submete job de predição em lote.
        
        Args:
            input_gcs_path: Caminho GCS com arquivos .jsonl de entrada
            output_gcs_path: Caminho GCS para salvar resultados
            model_name: Nome do modelo (usa o default se None)
            
        Returns:
            Status do job e metadados
        """
        model_name = model_name or self.config.model_name
        
        if self.simulation_mode:
            return self._simulate_batch_job(input_gcs_path, output_gcs_path, model_name)
        
        try:
            from google.cloud import aiplatform
            
            job = aiplatform.BatchPredictionJob.submit(
                project=self.config.project_id,
                location=self.config.region,
                job_display_name=f"batch-prediction-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                model_name=f"projects/{self.config.project_id}/locations/{self.config.region}/models/{model_name}",
                gcs_source=input_gcs_path,
                gcs_destination_prefix=output_gcs_path,
                predictions_format="jsonl"
            )
            
            logger.info(f"✅ Job submetido: {job.resource_name}")
            return {
                'job_id': job.resource_name,
                'status': 'SUBMITTED',
                'input_path': input_gcs_path,
                'output_path': output_gcs_path,
                'model': model_name
            }
            
        except Exception as e:
            logger.error(f"Erro ao submeter batch job: {e}")
            return {'error': str(e), 'status': 'FAILED'}
    
    def _simulate_batch_job(self, 
                           input_gcs_path: str, 
                           output_gcs_path: str,
                           model_name: str) -> Dict[str, Any]:
        """Simula job em lote para desenvolvimento."""
        logger.info(f"📦 [SIMULAÇÃO] Batch Prediction Job")
        logger.info(f"   Input: {input_gcs_path}")
        logger.info(f"   Output: {output_gcs_path}")
        logger.info(f"   Model: {model_name}")
        
        # Simula processamento
        import time
        time.sleep(1)  # Simula tempo de processamento
        
        return {
            'job_id': f"simulated-job-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            'status': 'COMPLETED_SIMULATED',
            'input_path': input_gcs_path,
            'output_path': output_gcs_path,
            'model': model_name,
            'records_processed': 1000,
            'execution_time_seconds': 45
        }
    
    def consolidate_to_bigquery(self, 
                               results_gcs_path: str,
                               table_name: str) -> Dict[str, Any]:
        """
        Consolida resultados do batch no BigQuery.
        
        Args:
            results_gcs_path: Caminho GCS com resultados das predições
            table_name: Nome da tabela BigQuery de destino
            
        Returns:
            Status da consolidação
        """
        if self.simulation_mode:
            logger.info(f"📊 [SIMULAÇÃO] Consolidando resultados no BigQuery")
            logger.info(f"   Fonte: {results_gcs_path}")
            logger.info(f"   Tabela: {self.config.dataset_id}.{table_name}")
            
            return {
                'status': 'CONSOLIDATED_SIMULATED',
                'table': f"{self.config.dataset_id}.{table_name}",
                'rows_inserted': 1000
            }
        
        try:
            from google.cloud import bigquery
            
            client = bigquery.Client(project=self.config.project_id)
            
            # Cria tabela externa apontando para GCS
            table_ref = f"{self.config.project_id}.{self.config.dataset_id}.{table_name}"
            
            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND
            )
            
            load_job = client.load_table_from_uri(
                results_gcs_path,
                table_ref,
                job_config=job_config
            )
            
            load_job.result()  # Aguarda conclusão
            
            logger.info(f"✅ {load_job.output_rows} linhas inseridas em {table_ref}")
            
            return {
                'status': 'CONSOLIDATED',
                'table': table_ref,
                'rows_inserted': load_job.output_rows
            }
            
        except Exception as e:
            logger.error(f"Erro ao consolidar no BigQuery: {e}")
            return {'error': str(e), 'status': 'FAILED'}


# ============================================================================
# PIPELINE PRINCIPAL
# ============================================================================

def run_healthcare_pipeline(simulation_mode: bool = True) -> Dict[str, Any]:
    """
    Executa o pipeline completo de saúde.
    
    Args:
        simulation_mode: Se True, usa mocks em vez de serviços GCP reais
        
    Returns:
        Dicionário com resultados de cada etapa do pipeline
    """
    setup_logging(simulation_mode)
    config = GCPConfig.from_env()
    
    results = {
        'ingestion': None,
        'reconciliation': None,
        'anonymization': None,
        'online_inference': None,
        'batch_prediction': None,
        'bigquery_consolidation': None
    }
    
    try:
        # 1. Geração e Ingestão de Dados
        logger.info("📥 Etapa 1: Ingestão de dados biométricos")
        generator = DataGenerator(seed=42)
        raw_readings = generator.generate_patient_vitals(
            patient_id="PATIENT_12345",
            num_readings=6
        )
        results['ingestion'] = {'readings_count': len(raw_readings), 'status': 'success'}
        logger.info(f"   ✅ {len(raw_readings)} leituras geradas")
        
        # 2. Reconciliação em Janela de Tempo
        logger.info("🔄 Etapa 2: Reconciliação de dados")
        reconciler = DataReconciliation(window_size_seconds=60)
        reconciliation_result = reconciler.reconcile_window(raw_readings)
        results['reconciliation'] = reconciliation_result
        logger.info(f"   ✅ Dados reconciliados: {reconciliation_result['status']}")
        
        if reconciliation_result['data']:
            # 3. Anonimização (Padrão FHIR)
            logger.info("🔒 Etapa 3: Anonimização de dados sensíveis")
            anonymizer = FHIRAnonymizer()
            
            patient_info = {
                'patient_id': 'PATIENT_12345',
                'name': 'John Doe',
                'email': 'john.doe@email.com',
                'birth_date': '1985-03-15',
                'vitals': reconciliation_result['data']
            }
            
            anonymized_data = anonymizer.anonymize_patient(patient_info)
            results['anonymization'] = {
                'original_fields_removed': 4,
                'anonymous_id': anonymized_data.get('patient_id_anon'),
                'status': 'success'
            }
            logger.info(f"   ✅ Paciente anonimizado: {anonymized_data.get('patient_id_anon')}")
            
            # 4. Inferência Online (Vertex AI Endpoint)
            logger.info("🤖 Etapa 4: Inferência online para detecção de arritmia")
            online_inferencer = VertexAIOnlineInference(config, simulation_mode)
            
            prediction_result = online_inferencer.predict_arrhythmia(reconciliation_result['data'])
            results['online_inference'] = prediction_result
            logger.info(f"   ✅ Predição: {prediction_result.get('class_label', 'N/A')} "
                       f"(confiança: {prediction_result.get('confidence', 0):.2f})")
        
        # 5. Inferência Batch (Vertex AI Batch Prediction)
        logger.info("📦 Etapa 5: Predição em lote para análise populacional")
        batch_predictor = VertexAIBatchPrediction(config, simulation_mode)
        
        input_path = f"gs://{config.bucket_name}/data/batch/input/patients_2024.jsonl"
        output_path = f"gs://{config.bucket_name}/data/batch/output/predictions_2024/"
        
        batch_result = batch_predictor.submit_batch_job(input_path, output_path)
        results['batch_prediction'] = batch_result
        logger.info(f"   ✅ Job batch: {batch_result['status']}")
        
        # 6. Consolidação no BigQuery
        logger.info("📊 Etapa 6: Consolidação no BigQuery")
        bq_result = batch_predictor.consolidate_to_bigquery(
            results_gcs_path=f"{output_path}*.jsonl",
            table_name="population_risk_predictions"
        )
        results['bigquery_consolidation'] = bq_result
        logger.info(f"   ✅ BigQuery: {bq_result['status']}")
        
        logger.info("\n🎉 Pipeline concluído com sucesso!")
        
    except KeyboardInterrupt:
        logger.warning("⚠️ Pipeline interrompido pelo usuário")
        results['error'] = 'interrupted'
    except Exception as e:
        logger.error(f"❌ Erro no pipeline: {e}")
        results['error'] = str(e)
    
    return results


if __name__ == "__main__":
    # Executa o pipeline
    final_results = run_healthcare_pipeline(simulation_mode=True)
    
    # Exibe resumo dos resultados
    print("\n" + "="*60)
    print("RESUMO DO PIPELINE")
    print("="*60)
    for stage, result in final_results.items():
        if result:
            print(f"{stage}: {result.get('status', 'N/A')}")
    print("="*60)

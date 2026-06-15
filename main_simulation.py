import time
import logging
import os
from typing import Optional
from dataclasses import dataclass
from src.utils.data_generator import generate_sensor_data, generate_patient_fhir_mock
from src.ingestion.data_reconciliation import reconciliar_dados_biometricos
from src.security.anonymization import anonimizar_paciente_fhir
from src.ml_pipeline.online_inference import VertexOnlineDetector
from src.ml_pipeline.batch_inference import orquestrar_batch_vertex_ai


@dataclass
class GCPConfig:
    """Configuração centralizada para credenciais e recursos do GCP."""
    project_id: str
    location: str
    vertex_endpoint_id: Optional[str] = None
    vertex_model_name: Optional[str] = None
    gcs_input_uri: Optional[str] = None
    gcs_output_uri: Optional[str] = None
    
    @classmethod
    def from_env(cls) -> 'GCPConfig':
        """Carrega configuração a partir de variáveis de ambiente."""
        return cls(
            project_id=os.getenv('GCP_PROJECT_ID', 'project-d28ce7a4-0717-428d-ae4'),
            location=os.getenv('GCP_LOCATION', 'us-central1'),
            vertex_endpoint_id=os.getenv('VERTEX_ENDPOINT_ID'),
            vertex_model_name=os.getenv('VERTEX_MODEL_NAME', 'modelo-saude-populacional-v2'),
            gcs_input_uri=os.getenv('GCS_INPUT_DATA'),
            gcs_output_uri=os.getenv('GCS_OUTPUT_DATA'),
        )


def configurar_logging(nivel: int = logging.INFO) -> None:
    """Configura logging formatado para toda a aplicação."""
    logging.basicConfig(
        level=nivel,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def run_simulation(config: Optional[GCPConfig] = None) -> dict:
    """
    Executa simulação completa do pipeline de saúde digital.
    
    Args:
        config: Configuração do GCP. Se None, usa variáveis de ambiente.
        
    Returns:
        Dict com resultados da execução.
    """
    if config is None:
        config = GCPConfig.from_env()
    
    logger = logging.getLogger(__name__)
    resultados = {
        'reconciliados': 0,
        'inferencias_online': 0,
        'batch_submitted': False,
        'erros': []
    }
    
    print("=" * 60)
    print(" INICIANDO INTEGRAÇÃO VERTEX AI (ESQUELETO DE PRODUÇÃO) ")
    print("=" * 60)
    logger.info(f"Projeto GCP: {config.project_id} | Região: {config.location}")

    try:
        # 1. Coleta e Unificação
        print("\n[1] GERANDO E UNIFICANDO DADOS (Ingestão)...")
        logger.info("Gerando dados de sensores biométricos...")
        df_raw = generate_sensor_data(num_records=10, seed=42)
        df_clean = reconciliar_dados_biometricos(df_raw, janela_tempo_segundos=3)
        resultados['reconciliados'] = len(df_clean)
        logger.info(f"{resultados['reconciliados']} leituras reconciliadas com sucesso")
        print(f"Dados reconciliados: {resultados['reconciliados']} batimentos consolidados para streaming.")

        # 2. Segurança
        print("\n[2] ANONIMIZAÇÃO (Privacidade FHIR)...")
        paciente_mock = generate_patient_fhir_mock()
        paciente_anonimo = anonimizar_paciente_fhir(paciente_mock)
        id_anonimo = paciente_anonimo.get('identifier', [{}])[0].get('value', 'N/A')
        logger.info(f"Paciente anonimizado com ID: {id_anonimo}")
        print("ID Seguro (Lakehouse):", id_anonimo)

        # 3. Inferência Online (Vertex AI Endpoint)
        print("\n[3] INFERÊNCIA ONLINE (Chamando API Vertex AI Endpoint)...")
        detector_online = VertexOnlineDetector(
            project=config.project_id,
            location=config.location,
            endpoint_id=config.vertex_endpoint_id or "1234567890123456789"
        )
        
        logger.info(f"Iniciando inferência online para {len(df_clean)} leituras...")
        for idx, row in df_clean.iterrows():
            bpm = int(row['heart_rate_reconciliado'])
            resultado = detector_online.processar_nova_leitura(bpm)
            resultados['inferencias_online'] += 1
            
            status_symbol = "⚠️" if resultado['alerta'] else "✓"
            print(f"  {status_symbol} BPM: {bpm:3d} | Score: {resultado['score']:.2f} | "
                  f"{resultado['status']} [{resultado['modo']}]")
            
            if resultado['alerta']:
                logger.warning(f"ALERTA: BPM={bpm}, score={resultado['score']:.2f}")
            
            # Em produção, usar async ou batch para múltiplas requisições
            time.sleep(0.1)

        # 4. Inferência Batch (Vertex AI Batch Prediction)
        print("\n[4] INFERÊNCIA EM LOTE (Submetendo Job no Vertex AI)...")
        
        if not config.gcs_input_uri or not config.gcs_output_uri:
            logger.warning("GCS URIs não configurados. Usando valores de exemplo.")
            gcs_input = "gs://seu-bucket-datalake/pacientes_fhir/dados_historicos.jsonl"
            gcs_output = "gs://seu-bucket-datalake/vertex_predictions/batch_risco/"
        else:
            gcs_input = config.gcs_input_uri
            gcs_output = config.gcs_output_uri
        
        resultado_batch = orquestrar_batch_vertex_ai(
            project=config.project_id,
            location=config.location,
            model_name=config.vertex_model_name or "modelo-saude-populacional-v2",
            gcs_input_uri=gcs_input,
            gcs_output_uri=gcs_output
        )
        
        resultados['batch_submitted'] = resultado_batch.get('status') == 'JOB_SUBMITTED'
        
        print("\n=> Status do Job Batch:")
        print(f"Status: {resultado_batch['status']}")
        if resultado_batch.get('job_url'):
            print(f"URL de Acompanhamento (GCP Console): {resultado_batch['job_url']}")
            logger.info(f"Batch job submetido: {resultado_batch.get('job_id', 'N/A')}")
        else:
            logger.warning(f"Batch em modo simulação: {resultado_batch.get('mensagem', '')}")
            print(f"Aviso: {resultado_batch.get('mensagem')}")
            print(f"Resultados seriam exportados para: {resultado_batch.get('gcs_output')}")

        print("\n" + "=" * 60)
        print(" FLUXO DE INTEGRAÇÃO COM A NUVEM CONCLUÍDO ")
        print("=" * 60)
        logger.info(f"Simulação concluída. Erros: {len(resultados['erros'])}")
        
        return resultados
        
    except Exception as e:
        logger.error(f"Erro durante simulação: {e}", exc_info=True)
        resultados['erros'].append(str(e))
        raise


if __name__ == "__main__":
    configurar_logging()
    try:
        run_simulation()
    except KeyboardInterrupt:
        print("\n\nExecução interrompida pelo usuário.")
    except Exception as e:
        print(f"\n❌ Falha na execução: {e}")
        exit(1)

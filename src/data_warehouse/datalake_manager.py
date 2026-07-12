import os
import pandas as pd
import logging
import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DataLakeManager:
    def __init__(self, lake_path='data/lake'):
        """
        Gerenciador do Data Lake com suporte a Google Cloud Storage (GCS) e local.
        Estrutura em camadas: raw, trusted, refined.
        """
        self.lake_path = lake_path
        
        if self.lake_path.startswith('gs://'):
            self.is_gcs = True
            # No GCS, a trusted_zone é uma URI gs://
            self.trusted_zone = self.lake_path.rstrip('/') + '/trusted/medical_literature'
            logger.info(f"DataLakeManager inicializado no modo GCP (GCS): {self.trusted_zone}")
        else:
            self.is_gcs = False
            self.trusted_zone = os.path.join(self.lake_path, 'trusted', 'medical_literature')
            os.makedirs(self.trusted_zone, exist_ok=True)
            logger.info(f"DataLakeManager inicializado no modo Local: {self.trusted_zone}")
            
    def ingest_csv_to_parquet(self, csv_filepath):
        """
        Lê um arquivo CSV de ingestão bruta e o converte para um formato colunar 
        particionado de alta performance (Parquet) no GCS ou local.
        """
        logger.info(f"Iniciando ingestão para o Data Lake: {csv_filepath}")
        if not os.path.exists(csv_filepath):
            logger.error(f"Arquivo fonte não encontrado: {csv_filepath}")
            return False
            
        try:
            df = pd.read_csv(csv_filepath)
            
            # Limpeza básica para o Data Lake
            df = df.dropna(subset=['resumo'])
            
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            
            if self.is_gcs:
                parquet_file = f"{self.trusted_zone}/ingestion_date={today}/data.parquet"
                logger.info(f"Salvando dados colunares diretamente no GCS: {parquet_file}")
                # Salva no GCS usando gcsfs automaticamente sob o capô
                df.to_parquet(parquet_file, engine='pyarrow', index=False)
            else:
                partition_path = os.path.join(self.trusted_zone, f'ingestion_date={today}')
                os.makedirs(partition_path, exist_ok=True)
                parquet_file = os.path.join(partition_path, 'data.parquet')
                df.to_parquet(parquet_file, engine='pyarrow', index=False)
                
            logger.info(f"Ingestão concluída. Arquivo salvo em: {parquet_file}")
            return parquet_file
        except Exception as e:
            logger.error(f"Falha na ingestão do Data Lake: {e}")
            # Em caso de erro de conexão com GCP, tentar fallback local se no modo GCS
            if self.is_gcs:
                logger.warning("Falha ao se conectar com o GCS. Tentando salvar no fallback local...")
                try:
                    local_path = os.path.join('data/lake', 'trusted', 'medical_literature', f'ingestion_date={today}')
                    os.makedirs(local_path, exist_ok=True)
                    local_file = os.path.join(local_path, 'data.parquet')
                    df.to_parquet(local_file, engine='pyarrow', index=False)
                    logger.info(f"Fallback concluído com sucesso. Salvo localmente em: {local_file}")
                    return local_file
                except Exception as local_err:
                    logger.error(f"Falha também no fallback local: {local_err}")
            return False

    def load_latest_knowledge(self):
        """Carrega todos os dados da camada Trusted (GCS ou local) para alimentar modelos de IA."""
        logger.info(f"Carregando literatura médica do Data Lake ({'GCS' if self.is_gcs else 'Local'})...")
        try:
            df = pd.read_parquet(self.trusted_zone, engine='pyarrow')
            return df
        except Exception as e:
            logger.warning(f"Data Lake ({self.trusted_zone}) pode estar vazio ou inacessível. {e}")
            if self.is_gcs:
                logger.info("Tentando carregar dados do fallback local (data/lake)...")
                try:
                    local_trusted = os.path.join('data/lake', 'trusted', 'medical_literature')
                    if os.path.exists(local_trusted):
                        return pd.read_parquet(local_trusted, engine='pyarrow')
                except Exception as local_err:
                    logger.warning(f"Falha ao carregar do fallback local: {local_err}")
            return pd.DataFrame()

if __name__ == "__main__":
    # Teste isolado
    dl = DataLakeManager()
    dl.ingest_csv_to_parquet('teses_usp_saude.csv')

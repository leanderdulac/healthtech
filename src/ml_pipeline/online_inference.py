import logging
from google.cloud import aiplatform
from google.api_core.exceptions import GoogleAPIError
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

class VertexOnlineDetector:
    def __init__(self, project: str, location: str, endpoint_id: str):
        """
        Inicializa o cliente do Vertex AI para inferência online de baixa latência.
        """
        self.project = project
        self.location = location
        self.endpoint_id = endpoint_id
        self.is_ready = False
        
        try:
            # Inicializa a conexão com o GCP
            aiplatform.init(project=project, location=location)
            # Instancia o Endpoint hospedado
            self.endpoint = aiplatform.Endpoint(endpoint_name=endpoint_id)
            self.is_ready = True
            logger.info(f"Conectado ao Vertex Endpoint: {endpoint_id}")
        except Exception as e:
            logger.warning(f"Aviso: Não foi possível autenticar no Vertex AI ({e}). Modo Simulação ativado.")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5), reraise=True)
    def _call_vertex_predict(self, instances):
        """Chama a API do Vertex com política de retry para falhas de rede."""
        return self.endpoint.predict(instances=instances)

    def processar_nova_leitura(self, valor_bpm: float) -> dict:
        """Envia um pulso para o Vertex AI para classificação em tempo real."""
        payload = {"instances": [{"bpm": valor_bpm}]}
        
        if self.is_ready:
            try:
                # Fazendo a inferência real na nuvem via REST/gRPC
                response = self._call_vertex_predict(payload["instances"])
                # Assumindo que o modelo retorna [is_anomaly_boolean, confidence_score]
                is_anomalia = response.predictions[0][0]
                score = response.predictions[0][1]
                
                return {
                    "alerta": is_anomalia,
                    "score": score,
                    "valor_atual": valor_bpm,
                    "status": "ALERTA CRÍTICO (Vertex)" if is_anomalia else "Normal",
                    "modo": "Produção GCP"
                }
            except GoogleAPIError as api_err:
                logger.error(f"Erro na API do Vertex: {api_err}")
                
        # Fallback de demonstração (Esqueleto local quando GCP não está logado)
        is_anomalia_mock = valor_bpm > 100 or valor_bpm < 40
        return {
            "alerta": is_anomalia_mock,
            "score": 0.99 if is_anomalia_mock else 0.1,
            "valor_atual": valor_bpm,
            "status": "ALERTA CRÍTICO (Mock)" if is_anomalia_mock else "Normal",
            "modo": "Simulação (Esqueleto)"
        }

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
        return self.processar_features({"bpm": valor_bpm})

    def processar_features(self, features: dict) -> dict:
        """Envia features completas do datalake para o Vertex AI Endpoint."""
        instance = {
            "bpm": float(features.get("bpm", 0)),
            "spo2": float(features.get("spo2", 97)),
            "hrv": float(features.get("hrv", 50)),
            "stress": float(features.get("stress", 0)),
            "quality_score": float(features.get("quality_score", 1.0)),
            "hour_of_day": int(features.get("hour_of_day", 12)),
            "is_active": int(features.get("is_active", 0)),
            "is_sleeping": int(features.get("is_sleeping", 0)),
        }

        if self.is_ready:
            try:
                response = self._call_vertex_predict([instance])
                prediction = response.predictions[0]
                if isinstance(prediction, (list, tuple)) and len(prediction) >= 2:
                    is_anomalia, score = prediction[0], prediction[1]
                elif isinstance(prediction, dict):
                    is_anomalia = prediction.get("is_anomaly", prediction.get("alerta", False))
                    score = prediction.get("score", prediction.get("anomaly_score", 0.5))
                else:
                    is_anomalia = bool(prediction)
                    score = 0.9 if is_anomalia else 0.1

                return {
                    "alerta": bool(is_anomalia),
                    "score": float(score),
                    "valor_atual": instance["bpm"],
                    "spo2": instance["spo2"],
                    "patient_id": features.get("patient_id"),
                    "timestamp": features.get("timestamp"),
                    "status": "ALERTA CRÍTICO (Vertex)" if is_anomalia else "Normal",
                    "modo": "Produção GCP",
                }
            except GoogleAPIError as api_err:
                logger.error("Erro na API do Vertex: %s", api_err)

        bpm = instance["bpm"]
        is_anomalia_mock = bpm > 100 or bpm < 40 or instance["spo2"] < 92
        return {
            "alerta": is_anomalia_mock,
            "score": 0.99 if is_anomalia_mock else 0.1,
            "valor_atual": bpm,
            "spo2": instance["spo2"],
            "patient_id": features.get("patient_id"),
            "timestamp": features.get("timestamp"),
            "status": "ALERTA CRÍTICO (Mock)" if is_anomalia_mock else "Normal",
            "modo": "Simulação (Esqueleto)",
        }

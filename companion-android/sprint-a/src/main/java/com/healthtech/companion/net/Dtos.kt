package com.healthtech.companion.net

/**
 * DTOs alinhados ao contrato OpenAPI HBand (ingest realtime mínimo — Sprint A).
 * @see docs/openapi/hband-wearable.yaml
 */
data class WearableIngestRequest(
    val patient_id: String,
    val device_id: String,
    val heart_rate: Double? = null,
    val spo2: Double? = null,
    val skin_temp: Double? = null,
    val hrv_rmssd: Double? = null,
    val activity_level: Double? = null,
    val filter_type: String? = "BMO",
    val timestamp: String? = null,
    val ppg_signal: List<Double>? = null,
)

/**
 * Subconjunto da resposta full/secure — campos úteis para log/UI no Sprint A.
 */
data class WearableIngestResponse(
    val patient_id: String? = null,
    val device_id: String? = null,
    val anomaly_detection: Map<String, Any?>? = null,
    val clinical_alerts: Map<String, Any?>? = null,
    val detail: String? = null,
    val error_code: String? = null,
)

data class ApiResult(
    val httpCode: Int,
    val body: String,
    val ok: Boolean,
) {
    val isUnauthorized: Boolean get() = httpCode == 401 || httpCode == 403
}

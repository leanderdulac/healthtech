package com.healthtech.companion.net

import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant

/**
 * DTOs de Telemetria do Wearable VE30 / HBand alinhados ao contrato OpenAPI e plataforma de IA Healthtech.
 */
data class WearableDeviceInfo(
    val device_id: String,
    val vendor: String = "hband",
    val model: String? = "VE30",
    val firmware_version: String? = null,
    val mac_address: String? = null,
    val battery_level: Double? = null,
    val origin_protocol_version: Int? = 3,
    val watchday: Int? = 7,
) {
    fun toJsonObject(): JSONObject = JSONObject().apply {
        put("device_id", device_id)
        put("vendor", vendor)
        model?.let { put("model", it) }
        firmware_version?.let { put("firmware_version", it) }
        mac_address?.let { put("mac_address", it) }
        battery_level?.let { put("battery_level", it) }
        origin_protocol_version?.let { put("origin_protocol_version", it) }
        watchday?.let { put("watchday", it) }
    }

    companion object {
        fun fromJsonObject(json: JSONObject): WearableDeviceInfo = WearableDeviceInfo(
            device_id = json.getString("device_id"),
            vendor = json.optString("vendor", "hband"),
            model = json.optStringOrNull("model"),
            firmware_version = json.optStringOrNull("firmware_version"),
            mac_address = json.optStringOrNull("mac_address"),
            battery_level = json.optNullableDouble("battery_level"),
            origin_protocol_version = json.optNullableInt("origin_protocol_version"),
            watchday = json.optNullableInt("watchday"),
        )
    }
}

internal fun JSONObject.optStringOrNull(key: String): String? =
    if (has(key) && !isNull(key)) getString(key) else null

internal fun JSONObject.optNullableDouble(key: String): Double? =
    if (has(key) && !isNull(key)) optDouble(key) else null

internal fun JSONObject.optNullableInt(key: String): Int? =
    if (has(key) && !isNull(key)) optInt(key) else null

/**
 * Envelope em Tempo Real completo enviado pelo VE30 para a IA HealthTech.
 */
data class WearableIngestRequest(
    val patient_id: String,
    val device_id: String,
    val heart_rate: Double? = null,
    val spo2: Double? = null,
    val skin_temp: Double? = null,
    val blood_pressure_sys: Double? = null,
    val blood_pressure_dia: Double? = null,
    val hrv_rmssd: Double? = null,
    val activity_level: Double? = null,
    val steps: Int? = null,
    val calories: Double? = null,
    val wear_status: Boolean = true,
    val ppg_signal: List<Double>? = null,
    val filter_type: String = "BMO",
    val timestamp: String = Instant.now().toString(),
    val device_info: WearableDeviceInfo? = null,
) {
    fun toJsonObject(): JSONObject = JSONObject().apply {
        put("patient_id", patient_id)
        put("device_id", device_id)
        heart_rate?.let { put("heart_rate", it) }
        spo2?.let { put("spo2", it) }
        skin_temp?.let { put("skin_temp", it) }
        blood_pressure_sys?.let { put("blood_pressure_sys", it) }
        blood_pressure_dia?.let { put("blood_pressure_dia", it) }
        hrv_rmssd?.let { put("hrv_rmssd", it) }
        activity_level?.let { put("activity_level", it) }
        steps?.let { put("steps", it) }
        calories?.let { put("calories", it) }
        put("wear_status", wear_status)
        put("filter_type", filter_type)
        put("timestamp", timestamp)
        ppg_signal?.let {
            val arr = JSONArray()
            it.forEach { sample -> arr.put(sample) }
            put("ppg_signal", arr)
        }
        device_info?.let { put("device", it.toJsonObject()) }
    }

    companion object {
        fun fromJsonObject(json: JSONObject): WearableIngestRequest {
            val ppg = json.optJSONArray("ppg_signal")?.let { arr ->
                (0 until arr.length()).map { arr.getDouble(it) }
            }
            return WearableIngestRequest(
                patient_id = json.getString("patient_id"),
                device_id = json.getString("device_id"),
                heart_rate = json.optNullableDouble("heart_rate"),
                spo2 = json.optNullableDouble("spo2"),
                skin_temp = json.optNullableDouble("skin_temp"),
                blood_pressure_sys = json.optNullableDouble("blood_pressure_sys"),
                blood_pressure_dia = json.optNullableDouble("blood_pressure_dia"),
                hrv_rmssd = json.optNullableDouble("hrv_rmssd"),
                activity_level = json.optNullableDouble("activity_level"),
                steps = json.optNullableInt("steps"),
                calories = json.optNullableDouble("calories"),
                wear_status = json.optBoolean("wear_status", true),
                ppg_signal = ppg,
                filter_type = json.optString("filter_type", "BMO"),
                timestamp = json.optString("timestamp", Instant.now().toString()),
                device_info = json.optJSONObject("device")?.let { WearableDeviceInfo.fromJsonObject(it) },
            )
        }
    }
}

/**
 * Amostra histórica de 5 minutos (OriginData3) lida da memória do VE30.
 */
data class OriginDataSample(
    val timestamp: String,
    val heart_rate: Double?,
    val spo2: Double?,
    val blood_pressure_sys: Double?,
    val blood_pressure_dia: Double?,
    val hrv: Double?,
    val step_count: Int?,
    val cal_value: Double?,
) {
    fun toJsonObject(): JSONObject = JSONObject().apply {
        put("timestamp", timestamp)
        heart_rate?.let { put("heart_rate", it) }
        spo2?.let { put("spo2", it) }
        blood_pressure_sys?.let { put("blood_pressure_sys", it) }
        blood_pressure_dia?.let { put("blood_pressure_dia", it) }
        hrv?.let { put("hrv", it) }
        step_count?.let { put("step_count", it) }
        cal_value?.let { put("cal_value", it) }
    }
}

data class WearableBatchIngestRequest(
    val patient_id: String,
    val device_id: String,
    val samples: List<OriginDataSample>,
) {
    fun toJsonObject(): JSONObject = JSONObject().apply {
        put("patient_id", patient_id)
        put("device_id", device_id)
        val arr = JSONArray()
        samples.forEach { arr.put(it.toJsonObject()) }
        put("readings", arr)
    }
}

/**
 * Resposta enriquecida da IA da plataforma HealthTech após processar a telemetria.
 */
data class AiInferenceResponse(
    val status: String,
    val patient_id: String?,
    val device_id: String?,
    val phantom_data: Map<String, PhantomStateEstimate>?,
    val anomaly_detection: Map<String, Any?>?,
    val diagnostic_hypotheses: List<Map<String, Any?>>?,
    val multi_agent_consensus: Map<String, Any?>?,
    val clinical_alerts: List<String>?,
    val detail: String?,
    val http_code: Int,
    val ok: Boolean,
)

data class PhantomStateEstimate(
    val estimate: Double,
    val ci_lower: Double,
    val ci_upper: Double,
    val is_reliable: Boolean,
)

data class ApiResult(
    val httpCode: Int,
    val body: String,
    val ok: Boolean,
    val parsedAiResponse: AiInferenceResponse? = null,
) {
    val isUnauthorized: Boolean get() = httpCode == 401 || httpCode == 403
    val isClientError: Boolean get() = httpCode in 400..499
    val isServerError: Boolean get() = httpCode >= 500
}
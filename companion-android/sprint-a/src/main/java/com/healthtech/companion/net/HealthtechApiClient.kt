package com.healthtech.companion.net

import org.json.JSONObject
import java.io.BufferedReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Cliente HTTP mínimo (sem dependência OkHttp no esboço).
 * Em produção prefira OkHttp + interceptor de X-API-Key.
 *
 * Base URL exemplos:
 *  - https://healthtech-responsive-5794833455.us-central1.run.app
 *  - https://healthtech-secure-api-5794833455.us-central1.run.app
 */
class HealthtechApiClient(
    private val baseUrl: String,
    private val apiKey: String,
    private val executor: ExecutorService = Executors.newSingleThreadExecutor(),
) {
    fun ingestRealtime(
        request: WearableIngestRequest,
        callback: (ApiResult) -> Unit,
    ) {
        executor.execute {
            callback(ingestRealtimeSync(request))
        }
    }

    fun ingestRealtimeSync(request: WearableIngestRequest): ApiResult {
        val url = URL("${baseUrl.trimEnd('/')}/api/v1/wearables/ingest")
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 20_000
            readTimeout = 30_000
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("X-API-Key", apiKey)
            setRequestProperty("Accept", "application/json")
        }
        val payload = JSONObject().apply {
            put("patient_id", request.patient_id)
            put("device_id", request.device_id)
            request.heart_rate?.let { put("heart_rate", it) }
            request.spo2?.let { put("spo2", it) }
            request.skin_temp?.let { put("skin_temp", it) }
            request.hrv_rmssd?.let { put("hrv_rmssd", it) }
            request.activity_level?.let { put("activity_level", it) }
            request.filter_type?.let { put("filter_type", it) }
            put("timestamp", request.timestamp ?: Instant.now().toString())
        }
        return try {
            OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(payload.toString()) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val body = stream?.bufferedReader()?.use(BufferedReader::readText).orEmpty()
            ApiResult(httpCode = code, body = body, ok = code in 200..299)
        } catch (e: Exception) {
            ApiResult(httpCode = 0, body = e.message ?: "network error", ok = false)
        } finally {
            conn.disconnect()
        }
    }

    /** Smoke local: envia BPM fake sem device. */
    fun smokeHeart(
        patientId: String,
        deviceId: String,
        bpm: Double = 78.0,
        callback: (ApiResult) -> Unit,
    ) {
        ingestRealtime(
            WearableIngestRequest(
                patient_id = patientId,
                device_id = deviceId,
                heart_rate = bpm,
                filter_type = "BMO",
            ),
            callback,
        )
    }
}

package com.healthtech.companion.net

import com.google.gson.Gson
import com.healthtech.companion.net.dto.ApiErrorBody
import com.healthtech.companion.net.dto.BatchIngestResponse
import com.healthtech.companion.net.dto.BmoAnalysisRequest
import com.healthtech.companion.net.dto.HealthResponse
import com.healthtech.companion.net.dto.PatientHistoryResponse
import com.healthtech.companion.net.dto.ProcessedTelemetry
import com.healthtech.companion.net.dto.WearableBatchIngestRequest
import com.healthtech.companion.net.dto.WearableIngestRequest
import retrofit2.Response
import java.time.Instant

/**
 * Camada de aplicação sobre [HealthtechApi].
 * Converte Response Retrofit → [ApiResult] e aplica defaults (timestamp).
 */
class HealthtechRepository(
    private val api: HealthtechApi,
    private val gson: Gson = HealthtechRetrofitFactory.gson(),
    private val writeApiKeyLabel: String = "ingest",
) {

    suspend fun health(): ApiResult<HealthResponse> = safeCall { api.health() }

    suspend fun ingest(request: WearableIngestRequest): ApiResult<ProcessedTelemetry> {
        val body = request.withDefaultTimestamp()
        return safeCall { api.ingest(body) }
    }

    suspend fun batchIngest(
        patientId: String,
        readings: List<WearableIngestRequest>,
    ): ApiResult<BatchIngestResponse> {
        require(readings.isNotEmpty()) { "readings não pode ser vazio" }
        require(readings.size <= 200) { "batch máximo 200 readings" }
        val normalized = readings.map {
            it.copy(patientId = patientId).withDefaultTimestamp()
        }
        return safeCall {
            api.batchIngest(WearableBatchIngestRequest(patientId, normalized))
        }
    }

    suspend fun latest(patientId: String): ApiResult<ProcessedTelemetry> =
        safeCall { api.latest(patientId) }

    suspend fun history(patientId: String, limit: Int = 20): ApiResult<PatientHistoryResponse> =
        safeCall { api.history(patientId, limit.coerceIn(1, 100)) }

    suspend fun bmoAnalysis(signal: List<Double>, scales: List<Int>? = null): ApiResult<Map<String, Any?>> =
        safeCall { api.bmoAnalysis(BmoAnalysisRequest(signal, scales)) }

    /** Smoke sem device: envia HR fake. */
    suspend fun smokeHeart(
        patientId: String,
        deviceId: String = "HBAND-SMOKE",
        bpm: Double = 78.0,
    ): ApiResult<ProcessedTelemetry> = ingest(
        WearableIngestRequest(
            patientId = patientId,
            deviceId = deviceId,
            heartRate = bpm,
            filterType = "BMO",
            ingestSource = "companion_manual",
        ),
    )

    private fun WearableIngestRequest.withDefaultTimestamp(): WearableIngestRequest =
        if (timestamp.isNullOrBlank()) copy(timestamp = Instant.now().toString()) else this

    private suspend fun <T> safeCall(block: suspend () -> Response<T>): ApiResult<T> {
        return try {
            val response = block()
            val requestId = response.headers()["X-Request-ID"]
                ?: response.headers()["x-request-id"]
            if (response.isSuccessful) {
                val body = response.body()
                if (body != null) {
                    ApiResult.Success(body, response.code(), requestId)
                } else {
                    ApiResult.Failure(
                        httpCode = response.code(),
                        message = "Resposta vazia (HTTP ${response.code()})",
                        requestId = requestId,
                    )
                }
            } else {
                val raw = response.errorBody()?.string().orEmpty()
                val parsed = runCatching { gson.fromJson(raw, ApiErrorBody::class.java) }.getOrNull()
                val detailMsg = when (val d = parsed?.detail) {
                    is String -> d
                    null -> raw.ifBlank { "HTTP ${response.code()}" }
                    else -> d.toString()
                }
                ApiResult.Failure(
                    httpCode = response.code(),
                    message = detailMsg,
                    errorCode = parsed?.errorCode,
                    requestId = parsed?.requestId ?: requestId,
                    body = raw,
                )
            }
        } catch (e: Exception) {
            ApiResult.Failure(
                httpCode = 0,
                message = e.message ?: "network error",
                throwable = e,
            )
        }
    }

    companion object {
        fun create(
            baseUrl: String = HealthtechRetrofitFactory.DEFAULT_LOCAL_BASE,
            apiKey: String,
            enableHttpLogging: Boolean = false,
        ): HealthtechRepository {
            val api = HealthtechRetrofitFactory.createApi(baseUrl, apiKey, enableHttpLogging)
            return HealthtechRepository(api)
        }
    }
}

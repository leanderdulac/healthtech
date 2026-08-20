package com.healthtech.companion.net

import com.healthtech.companion.net.dto.BatchIngestResponse
import com.healthtech.companion.net.dto.BmoAnalysisRequest
import com.healthtech.companion.net.dto.BmoDenoiseRequest
import com.healthtech.companion.net.dto.BmoHrvRequest
import com.healthtech.companion.net.dto.HealthResponse
import com.healthtech.companion.net.dto.PatientHistoryResponse
import com.healthtech.companion.net.dto.ProcessedTelemetry
import com.healthtech.companion.net.dto.WearableBatchIngestRequest
import com.healthtech.companion.net.dto.WearableIngestRequest
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Contrato REST Healthtech para companion mobile.
 *
 * Auth: header X-API-Key injetado pelo [HealthtechRetrofitFactory]
 * (exceto [health], que é público).
 */
interface HealthtechApi {

    @GET("api/health")
    suspend fun health(): Response<HealthResponse>

    @POST("api/v1/wearables/ingest")
    suspend fun ingest(
        @Body body: WearableIngestRequest,
    ): Response<ProcessedTelemetry>

    @POST("api/v1/wearables/batch-ingest")
    suspend fun batchIngest(
        @Body body: WearableBatchIngestRequest,
    ): Response<BatchIngestResponse>

    @GET("api/v1/wearables/patient/{patient_id}/latest")
    suspend fun latest(
        @Path("patient_id") patientId: String,
    ): Response<ProcessedTelemetry>

    @GET("api/v1/wearables/patient/{patient_id}/history")
    suspend fun history(
        @Path("patient_id") patientId: String,
        @Query("limit") limit: Int = 20,
    ): Response<PatientHistoryResponse>

    @POST("api/v1/signal/bmo-analysis")
    suspend fun bmoAnalysis(
        @Body body: BmoAnalysisRequest,
    ): Response<Map<String, Any?>>

    @POST("api/v1/signal/bmo-denoise")
    suspend fun bmoDenoise(
        @Body body: BmoDenoiseRequest,
    ): Response<Map<String, Any?>>

    @POST("api/v1/signal/hrv/bmo-metrics")
    suspend fun hrvBmoMetrics(
        @Body body: BmoHrvRequest,
    ): Response<Map<String, Any?>>
}

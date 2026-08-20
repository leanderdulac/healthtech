package com.healthtech.companion.net.dto

import com.google.gson.annotations.SerializedName

/**
 * Modelos alinhados a:
 * - saude_responsiva_secure/app/models/schemas.py
 * - docs/openapi/hband-wearable.yaml
 */

data class WearableIngestRequest(
    @SerializedName("patient_id") val patientId: String,
    @SerializedName("device_id") val deviceId: String? = "wrist_wearable",
    @SerializedName("heart_rate") val heartRate: Double,
    @SerializedName("hrv_rmssd") val hrvRmssd: Double? = null,
    @SerializedName("skin_temp") val skinTemp: Double? = null,
    @SerializedName("spo2") val spo2: Double? = null,
    @SerializedName("activity_level") val activityLevel: Double? = null,
    @SerializedName("ppg_signal") val ppgSignal: List<Double>? = null,
    @SerializedName("filter_type") val filterType: String? = "BMO",
    @SerializedName("timestamp") val timestamp: String? = null,
    @SerializedName("blood_pressure_sys") val bloodPressureSys: Double? = null,
    @SerializedName("blood_pressure_dia") val bloodPressureDia: Double? = null,
    @SerializedName("glucose_mgdl") val glucoseMgdl: Double? = null,
    @SerializedName("body_temp_c") val bodyTempC: Double? = null,
    @SerializedName("steps_drop_pct") val stepsDropPct: Double? = null,
    @SerializedName("sleep_worsen_pct") val sleepWorsenPct: Double? = null,
    @SerializedName("ingest_source") val ingestSource: String? = "companion_manual",
)

data class WearableBatchIngestRequest(
    @SerializedName("patient_id") val patientId: String,
    @SerializedName("readings") val readings: List<WearableIngestRequest>,
)

data class BmoAnalysisRequest(
    @SerializedName("signal") val signal: List<Double>,
    @SerializedName("scales") val scales: List<Int>? = null,
)

data class BmoDenoiseRequest(
    @SerializedName("signal") val signal: List<Double>,
    @SerializedName("window_size") val windowSize: Int = 8,
    @SerializedName("alpha") val alpha: Double = 0.5,
)

data class BmoHrvRequest(
    @SerializedName("rr_intervals") val rrIntervals: List<Double>,
)

data class HealthResponse(
    @SerializedName("status") val status: String? = null,
    @SerializedName("service") val service: String? = null,
    @SerializedName("version") val version: String? = null,
)

/**
 * Resposta de ingest (secure e full). Campos extras do full chegam como Map.
 */
data class ProcessedTelemetry(
    @SerializedName("patient_id") val patientId: String? = null,
    @SerializedName("device_id") val deviceId: String? = null,
    @SerializedName("timestamp") val timestamp: String? = null,
    @SerializedName("raw_telemetry") val rawTelemetry: Map<String, Any?>? = null,
    @SerializedName("cleaned_telemetry") val cleanedTelemetry: Map<String, Any?>? = null,
    @SerializedName("phantom_data") val phantomData: Map<String, Any?>? = null,
    @SerializedName("anomaly_detection") val anomalyDetection: Map<String, Any?>? = null,
    @SerializedName("clinical_alerts") val clinicalAlerts: Map<String, Any?>? = null,
    @SerializedName("detail") val detail: String? = null,
    @SerializedName("error_code") val errorCode: String? = null,
    @SerializedName("request_id") val requestId: String? = null,
)

data class BatchIngestResponse(
    @SerializedName("status") val status: String? = null,
    @SerializedName("patient_id") val patientId: String? = null,
    @SerializedName("processed_count") val processedCount: Int? = null,
    @SerializedName("latest_result") val latestResult: ProcessedTelemetry? = null,
)

data class PatientHistoryResponse(
    @SerializedName("patient_id") val patientId: String? = null,
    @SerializedName("total_records") val totalRecords: Int? = null,
    @SerializedName("records") val records: List<ProcessedTelemetry>? = null,
)

data class ApiErrorBody(
    @SerializedName("detail") val detail: Any? = null,
    @SerializedName("error_code") val errorCode: String? = null,
    @SerializedName("request_id") val requestId: String? = null,
)

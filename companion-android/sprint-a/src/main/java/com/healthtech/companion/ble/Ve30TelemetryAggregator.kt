package com.healthtech.companion.ble

import android.util.Log
import com.healthtech.companion.net.HealthtechApiClient
import com.healthtech.companion.net.WearableDeviceInfo
import com.healthtech.companion.net.WearableIngestRequest
import java.time.Instant
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

/**
 * Agregador Multimodal de Sinais Vitais do VE30.
 * 
 * Problema Resolvido:
 *  Os sensores do relógio (HR, SpO2, Temp, Pressão Arterial, HRV e PPG) disparam callbacks
 *  em intervalos de tempo assíncronos. Este módulo mantém um buffer de estado fisiológico
 *  coerente e despacha snapshots consolidados para a API de IA a cada 2-3 segundos.
 */
class Ve30TelemetryAggregator(
    private val connection: HbandConnectionManager,
    private val apiClient: HealthtechApiClient,
    private val patientId: String,
    private val publishIntervalMs: Long = 2_500L,
) {
    interface AggregatorCallback {
        fun onTelemetryDispatched(request: WearableIngestRequest)
        fun onAiResponseReceived(heartRate: Double?, spo2: Double?, alerts: List<String>?, phantomBp: String?)
        fun onError(message: String)
    }

    private var callback: AggregatorCallback? = null
    private val scheduler = Executors.newSingleThreadScheduledExecutor()
    private var scheduledTask: ScheduledFuture<*>? = null

    // Buffers voláteis dos sensores
    @Volatile private var latestHeartRate: Double? = null
    @Volatile private var latestSpo2: Double? = null
    @Volatile private var latestSkinTemp: Double? = null
    @Volatile private var latestBpSys: Double? = null
    @Volatile private var latestBpDia: Double? = null
    @Volatile private var latestHrvRmssd: Double? = null
    @Volatile private var latestSteps: Int? = null
    @Volatile private var latestCalories: Double? = null
    @Volatile private var isWatchOnWrist: Boolean = true
    @Volatile private var batteryLevel: Double = 85.0

    private val ppgBuffer = ConcurrentHashMap.newKeySet<Double>()

    fun setCallback(cb: AggregatorCallback?) {
        this.callback = cb
    }

    fun start() {
        if (scheduledTask != null && !scheduledTask!!.isCancelled) return
        Log.i(TAG, "Iniciando agregador de telemetria VE30 (intervalo: ${publishIntervalMs}ms)...")
        scheduledTask = scheduler.scheduleWithFixedDelay(
            { dispatchConsolidatedTelemetry() },
            1000L,
            publishIntervalMs,
            TimeUnit.MILLISECONDS
        )
    }

    fun stop() {
        Log.i(TAG, "Parando agregador de telemetria...")
        scheduledTask?.cancel(true)
        scheduledTask = null
    }

    // Ingestão individual a partir dos listeners do SDK
    fun updateHeartRate(bpm: Double, wearStatus: Boolean = true) {
        if (bpm in 25.0..250.0) {
            this.latestHeartRate = bpm
            this.isWatchOnWrist = wearStatus
        }
    }

    fun updateSpo2(spo2Percent: Double) {
        if (spo2Percent in 50.0..100.0) {
            this.latestSpo2 = spo2Percent
        }
    }

    fun updateTemperature(skinTempC: Double) {
        if (skinTempC in 25.0..45.0) {
            this.latestSkinTemp = skinTempC
        }
    }

    fun updateBloodPressure(systolic: Double, diastolic: Double) {
        if (systolic in 60.0..260.0 && diastolic in 30.0..160.0) {
            this.latestBpSys = systolic
            this.latestBpDia = diastolic
        }
    }

    fun updateHrv(rmssd: Double) {
        if (rmssd in 0.0..300.0) {
            this.latestHrvRmssd = rmssd
        }
    }

    fun updateStepsAndCalories(steps: Int, calories: Double) {
        this.latestSteps = steps
        this.latestCalories = calories
    }

    fun updateBattery(level: Double) {
        this.batteryLevel = level
    }

    fun appendPpgSample(sample: Double) {
        if (ppgBuffer.size < 64) {
            ppgBuffer.add(sample)
        }
    }

    private fun dispatchConsolidatedTelemetry() {
        if (!connection.isReady) return

        val hr = latestHeartRate ?: 72.0
        val ppgList = if (ppgBuffer.isNotEmpty()) {
            val list = ppgBuffer.toList()
            ppgBuffer.clear()
            list
        } else null

        val mac = connection.currentMac() ?: "VE30-DEFAULT"
        val deviceId = if (mac.startsWith("HBAND-") || mac.startsWith("VE30-")) mac else "VE30-$mac"

        val request = WearableIngestRequest(
            patient_id = patientId,
            device_id = deviceId,
            heart_rate = hr,
            spo2 = latestSpo2 ?: 98.0,
            skin_temp = latestSkinTemp ?: 33.2,
            blood_pressure_sys = latestBpSys,
            blood_pressure_dia = latestBpDia,
            hrv_rmssd = latestHrvRmssd ?: 42.0,
            activity_level = if ((latestSteps ?: 0) > 0) 1.2 else 0.0,
            steps = latestSteps,
            calories = latestCalories,
            wear_status = isWatchOnWrist,
            ppg_signal = ppgList,
            filter_type = "BMO",
            timestamp = Instant.now().toString(),
            device_info = WearableDeviceInfo(
                device_id = deviceId,
                vendor = "hband",
                model = "VE30",
                battery_level = batteryLevel,
                mac_address = mac
            )
        )

        callback?.onTelemetryDispatched(request)

        apiClient.ingestRealtime(request) { result ->
            if (result.ok) {
                val parsed = result.parsedAiResponse
                var phantomBp: String? = null
                val pData = parsed?.phantom_data
                if (pData != null && pData.containsKey("systolic_bp") && pData.containsKey("diastolic_bp")) {
                    val sbp = pData["systolic_bp"]?.estimate ?: 120.0
                    val dbp = pData["diastolic_bp"]?.estimate ?: 80.0
                    phantomBp = "${sbp.toInt()}/${dbp.toInt()} mmHg (UKF)"
                }
                callback?.onAiResponseReceived(
                    heartRate = request.heart_rate,
                    spo2 = request.spo2,
                    alerts = parsed?.clinical_alerts,
                    phantomBp = phantomBp
                )
            } else {
                callback?.onError("Erro no envio à IA (${result.httpCode}): ${result.body.take(120)}")
            }
        }
    }

    companion object {
        private const val TAG = "Ve30TelemetryAggregator"
    }
}
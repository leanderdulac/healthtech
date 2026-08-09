package com.healthtech.companion.ble

import android.util.Log
import com.healthtech.companion.net.HealthtechApiClient
import com.healthtech.companion.net.WearableIngestRequest

/**
 * Coleta realtime mínima Sprint A: apenas HR.
 *
 * SDK real:
 *  manager.startDetectHeart(true, object : IHeartDataListener {
 *    override fun onDataChange(data: HeartData) { … data.data = BPM }
 *  })
 */
class HbandRealtimeCollector(
    private val connection: HbandConnectionManager,
    private val api: HealthtechApiClient,
    private val patientId: String,
) {
    interface UiCallback {
        fun onBpm(bpm: Double)
        fun onIngestResult(code: Int, bodyPreview: String)
        fun onError(message: String)
    }

    private var ui: UiCallback? = null
    private var lastSentAtMs: Long = 0L
    private val minIntervalMs: Long = 3_000

    fun setUiCallback(cb: UiCallback?) {
        ui = cb
    }

    fun startHeart() {
        if (!connection.isReady) {
            ui?.onError("Device não está ready (pwd/personInfo pendente)")
            return
        }
        // TODO: VPOperateManager.startDetectHeart(...)
        Log.i(TAG, "startHeart() — stub SDK; use pushHeartFromSdk() no listener real")
    }

    fun stopHeart() {
        // TODO: stopDetectHeart
    }

    /**
     * Chamar a partir do listener nativo do SDK com o BPM.
     * Debounce de 3s para não saturar a API.
     */
    fun pushHeartFromSdk(bpm: Double) {
        ui?.onBpm(bpm)
        val now = System.currentTimeMillis()
        if (now - lastSentAtMs < minIntervalMs) return
        lastSentAtMs = now

        val mac = connection.currentMac() ?: "HBAND-UNKNOWN"
        val deviceId = if (mac.startsWith("HBAND-")) mac else "HBAND-$mac"
        val req = WearableIngestRequest(
            patient_id = patientId,
            device_id = deviceId,
            heart_rate = bpm,
            filter_type = "BMO",
        )
        api.ingestRealtime(req) { result ->
            val preview = result.body.take(200)
            ui?.onIngestResult(result.httpCode, preview)
            if (result.isUnauthorized) {
                ui?.onError("Auth falhou (${result.httpCode}): confira INGEST_API_KEY / escopo wearables:write")
            } else if (!result.ok) {
                ui?.onError("Ingest falhou (${result.httpCode}): $preview")
            }
        }
    }

    companion object {
        private const val TAG = "HbandRealtime"
    }
}

package com.healthtech.companion.ble

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.random.Random

/**
 * Simula um wearable no próprio app.
 *
 * O dashboard trata `ingest_source=ble_sim` como device simulado — nunca como
 * pairing HBand físico.
 */
class SimulatedBleTransport(
    private val scope: CoroutineScope,
    private val deviceId: String,
    private val intervalMs: Long = 3_000,
    private val listener: BleSampleListener,
    private val status: BleStatusListener? = null,
) : BleTransport {

    override val mode: BleMode = BleMode.SIMULATOR

    @Volatile
    override var isRunning: Boolean = false
        private set

    private var job: Job? = null

    override fun start() {
        if (isRunning) return
        isRunning = true
        status?.onStatus("Simulador BLE iniciado (sem rádio). ingest_source=ble_sim")
        job = scope.launch {
            var bpm = 72.0
            while (isActive && isRunning) {
                bpm = (bpm + Random.nextDouble(-3.0, 3.0)).coerceIn(58.0, 110.0)
                listener.onHeartRate(kotlin.math.round(bpm), deviceId, "ble_sim")
                delay(intervalMs)
            }
        }
    }

    override fun stop() {
        isRunning = false
        job?.cancel()
        job = null
        status?.onStatus("Simulador BLE parado.")
    }
}

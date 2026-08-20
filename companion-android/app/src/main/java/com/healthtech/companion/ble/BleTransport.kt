package com.healthtech.companion.ble

/**
 * Porta BLE do companion.
 *
 * [SimulatedBleTransport] fecha o pipeline Device → App → API sem pulseira.
 * [HbandSdkTransport] é o gancho do SDK real (AARs Veepoo); sem AAR não finge pairing.
 */
interface BleTransport {
    val mode: BleMode
    val isRunning: Boolean
    fun start()
    fun stop()
}

fun interface BleSampleListener {
    fun onHeartRate(bpm: Double, deviceId: String, ingestSource: String)
}

fun interface BleStatusListener {
    fun onStatus(message: String)
}

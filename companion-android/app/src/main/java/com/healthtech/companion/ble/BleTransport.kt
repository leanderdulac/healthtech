package com.healthtech.companion.ble

/**
 * Porta BLE do companion.
 *
 * [SimulatedBleTransport] fecha o pipeline Device → App → API sem pulseira.
 * [HbandProtocolClient] faz o handshake Veepoo real (AARs em app/libs).
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

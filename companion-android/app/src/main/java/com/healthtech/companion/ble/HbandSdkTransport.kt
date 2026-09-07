package com.healthtech.companion.ble

/** @deprecated Use [HbandProtocolClient]. */
@Deprecated("Use HbandProtocolClient")
class HbandSdkTransport(
    private val status: BleStatusListener,
) : BleTransport {
    override val mode: BleMode = BleMode.HBAND_SDK
    @Volatile override var isRunning: Boolean = false
        private set

    override fun start() {
        status.onStatus("Use Escanear + Conectar. Handshake Veepoo é automático.")
    }

    override fun stop() {
        isRunning = false
    }
}

package com.healthtech.companion.ble

/**
 * Gancho do SDK HBand/Veepoo.
 *
 * Sem os AARs oficiais no classpath isto **não emite vitais** e não marca
 * `ingest_source=ble_hband`. Use [SimulatedBleTransport] para o pipeline.
 *
 * Sequência real (serial — nunca paralelo):
 * init → scan → connect → bleNotify OK → confirmDevicePwd("0000")
 * → syncPersonInfo → startDetectHeart → ingest_source=ble_hband
 */
class HbandSdkTransport(
    private val status: BleStatusListener,
) : BleTransport {

    override val mode: BleMode = BleMode.HBAND_SDK

    @Volatile
    override var isRunning: Boolean = false
        private set

    override fun start() {
        isRunning = false
        status.onStatus(
            "HBand SDK ausente neste APK. Adicione os AARs Veepoo " +
                "(VPOperateManager) e implemente o listener nativo. " +
                "Enquanto isso, use o simulador BLE — ele não finge pairing físico.",
        )
    }

    override fun stop() {
        isRunning = false
        // TODO: VPOperateManager.disconnectWatch()
    }

    fun sdkAvailable(): Boolean = false
}

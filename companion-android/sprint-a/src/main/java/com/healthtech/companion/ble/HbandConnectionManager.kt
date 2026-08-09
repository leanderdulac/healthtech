package com.healthtech.companion.ble

import android.content.Context
import android.util.Log

/**
 * Fachada da sequência obrigatória de conexão HBand/Veepoo.
 *
 * Integração real (preencher com AARs do SDK):
 *  1. VPOperateManager.getMangerInstance(appContext)
 *  2. startScanDevice()
 *  3. connectDevice(mac)
 *  4. aguardar bleNotifyResponse OK
 *  5. confirmDevicePwd("0000", …)
 *  6. syncPersonInfo(height, weight, age, sex)
 *  7. cache originProtocolVersion / watchday
 *  8. registerConnectStatusListener (reconnect)
 *
 * Serializar todas as operações BLE — sem paralelo.
 */
class HbandConnectionManager(
    private val appContext: Context,
) {
    interface Listener {
        fun onScanResult(mac: String, name: String?)
        fun onConnected(mac: String)
        fun onReady(mac: String) // pós pwd + personInfo
        fun onDisconnected(mac: String, reason: String?)
        fun onError(message: String)
    }

    private var listener: Listener? = null
    private var connectedMac: String? = null
    @Volatile var isReady: Boolean = false
        private set

    fun setListener(l: Listener?) {
        listener = l
    }

    fun initSdk() {
        // TODO: VPOperateManager.getMangerInstance(appContext.applicationContext)
        Log.i(TAG, "initSdk() — plugue VPOperateManager aqui")
    }

    fun startScan() {
        // TODO: manager.startScanDevice(scanCallback)
        Log.i(TAG, "startScan() — stub; emule com onScanResult em debug")
    }

    fun stopScan() {
        // TODO: manager.stopScanDevice()
    }

    fun connect(mac: String) {
        connectedMac = mac
        // TODO: manager.connectDevice(mac, connectCallback)
        // Na callback de notify OK → confirmDevicePwd → syncPersonInfo → markReady()
        Log.i(TAG, "connect($mac) — stub")
    }

    fun disconnect() {
        isReady = false
        connectedMac = null
        // TODO: manager.disconnectWatch()
    }

    /** Chamado após pwd + personInfo bem-sucedidos. */
    fun markReady(mac: String) {
        isReady = true
        connectedMac = mac
        listener?.onReady(mac)
    }

    fun currentMac(): String? = connectedMac

    companion object {
        private const val TAG = "HbandConnection"
        const val DEFAULT_PWD = "0000"
    }
}

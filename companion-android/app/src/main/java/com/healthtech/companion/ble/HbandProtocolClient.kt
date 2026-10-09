package com.healthtech.companion.ble

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import com.inuker.bluetooth.library.Code
import com.inuker.bluetooth.library.Constants
import com.inuker.bluetooth.library.model.BleGattProfile
import com.inuker.bluetooth.library.search.SearchResult
import com.inuker.bluetooth.library.search.response.SearchResponse
import com.veepoo.protocol.VPOperateManager
import com.veepoo.protocol.listener.base.IABleConnectStatusListener
import com.veepoo.protocol.listener.base.IBleWriteResponse
import com.veepoo.protocol.listener.base.IConnectResponse
import com.veepoo.protocol.listener.base.INotifyResponse
import com.veepoo.protocol.listener.data.IDeviceFuctionDataListener
import com.veepoo.protocol.listener.data.IHeartDataListener
import com.veepoo.protocol.listener.data.IPersonInfoDataListener
import com.veepoo.protocol.listener.data.IPwdDataListener
import com.veepoo.protocol.listener.data.ISocialMsgDataListener
import com.veepoo.protocol.listener.data.ICustomSettingDataListener
import com.veepoo.protocol.listener.data.ISpo2hDataListener
import com.veepoo.protocol.model.datas.DeviceFunctionPackage1
import com.veepoo.protocol.model.datas.DeviceFunctionPackage2
import com.veepoo.protocol.model.datas.DeviceFunctionPackage3
import com.veepoo.protocol.model.datas.DeviceFunctionPackage4
import com.veepoo.protocol.model.datas.DeviceFunctionPackage5
import com.veepoo.protocol.model.datas.FunctionDeviceSupportData
import com.veepoo.protocol.model.datas.FunctionSocailMsgData
import com.veepoo.protocol.model.datas.HeartData
import com.veepoo.protocol.model.datas.PersonInfoData
import com.veepoo.protocol.model.datas.PwdData
import com.veepoo.protocol.model.datas.Spo2hData
import com.veepoo.protocol.model.enums.EHeartStatus
import com.veepoo.protocol.model.enums.EOprateStauts
import com.veepoo.protocol.model.enums.EPwdStatus
import com.veepoo.protocol.model.enums.ESex
import com.veepoo.protocol.model.settings.CustomSettingData

/**
 * Cliente HBand/Veepoo com a sequência **serial** obrigatória.
 *
 * scan → connect → bleNotify OK → confirmDevicePwd("0000") → syncPersonInfo
 * → (1.2s) → startDetectHeart.
 *
 * SpO2 entra em série: depois de uma FC normal, para o coração, mede SpO2
 * e só então religa a FC. O SDK não aceita as duas ao mesmo tempo.
 *
 * Só emite BPM quando [EHeartStatus.STATE_HEART_NORMAL] e o valor está em 20–250.
 * STATE_INIT / DETECT / BUSY devolvem 0 ou lixo — isso era a leitura "errada".
 */
class HbandProtocolClient(
    context: Context,
    private val listener: Listener,
) {
    interface Listener {
        fun onScanStarted()
        fun onDeviceFound(device: ScannedDevice)
        fun onScanFinished()
        fun onStatus(message: String)
        fun onReady(mac: String)
        fun onHeartRate(bpm: Int, mac: String, status: String)
        fun onSpo2(percent: Int, mac: String)
        fun onDisconnected(mac: String, reason: String?)
        fun onError(message: String)
    }

    private val appContext = context.applicationContext
    private val handler = Handler(Looper.getMainLooper())
    private val manager: VPOperateManager = VPOperateManager.getInstance()

    @Volatile var connectedMac: String? = null
        private set

    @Volatile var isReady: Boolean = false
        private set

    @Volatile private var heartRunning = false
    @Volatile private var handshakeGen = 0
    private val spo2Cycle = Spo2Cycle()
    private var spo2Timeout: Runnable? = null

    private val writeAck = IBleWriteResponse { code ->
        if (code != Code.REQUEST_SUCCESS) {
            Log.w(TAG, "write code=$code (${Code.toString(code)})")
        }
    }

    private val connectStatus = object : IABleConnectStatusListener() {
        override fun onConnectStatusChanged(mac: String?, status: Int) {
            if (status == Constants.STATUS_DISCONNECTED) {
                val lost = mac ?: connectedMac
                val gen = handshakeGen
                handler.post {
                    if (gen != handshakeGen) return@post
                    if (lost.isNullOrBlank() || lost != connectedMac) return@post
                    resetHandshake("link dropped")
                    listener.onDisconnected(lost, "BLE desconectou")
                }
            }
        }
    }

    fun initSdk() {
        manager.init(appContext)
    }

    fun startScan() {
        manager.stopScanDevice()
        manager.startScanDevice(object : SearchResponse {
            override fun onSearchStarted() {
                handler.post { listener.onScanStarted() }
            }

            override fun onDeviceFounded(result: SearchResult?) {
                if (result == null) return
                val mac = result.address ?: return
                val name = result.name ?: ""
                val score = wearableScore(name)
                handler.post {
                    listener.onDeviceFound(
                        ScannedDevice(
                            mac = mac,
                            name = name.ifBlank { "N/A" },
                            rssi = result.rssi,
                            wearableLikely = score > 0,
                        ),
                    )
                }
            }

            override fun onSearchStopped() {
                handler.post { listener.onScanFinished() }
            }

            override fun onSearchCanceled() {
                handler.post { listener.onScanFinished() }
            }
        })
    }

    fun stopScan() {
        manager.stopScanDevice()
    }

    fun connect(mac: String, name: String?) {
        stopScan()
        handler.removeCallbacksAndMessages(null)
        disconnectInternal()
        val gen = ++handshakeGen
        connectedMac = mac
        listener.onStatus("Conectando $mac…")
        manager.connectDevice(
            mac,
            name,
            IConnectResponse { code, _: BleGattProfile?, _ ->
                handler.post {
                    if (gen != handshakeGen) return@post
                    if (code != Code.REQUEST_SUCCESS) {
                        listener.onError(
                            "Falha ao conectar ($code). " +
                                "Escolha a pulseira, não fone/TV/outro BLE.",
                        )
                    } else {
                        listener.onStatus("GATT ok. Aguardando notify (handshake)…")
                        manager.registerConnectStatusListener(mac, connectStatus)
                    }
                }
            },
            INotifyResponse { state ->
                handler.post {
                    if (gen != handshakeGen) return@post
                    if (state != Code.REQUEST_SUCCESS) {
                        listener.onError(
                            "Notify BLE falhou ($state). Sem notify o device não envia vitais.",
                        )
                        return@post
                    }
                    listener.onStatus("Notify ok. Validando o acesso do dispositivo…")
                    confirmPassword(mac, gen)
                }
            },
        )
    }

    fun disconnect() {
        handshakeGen++
        handler.removeCallbacksAndMessages(null)
        stopHeartInternal()
        disconnectInternal()
    }

    fun startHeart() {
        val mac = connectedMac
        if (!isReady || mac == null) {
            listener.onError("Device ainda não está ready (senha/personInfo).")
            return
        }
        if (heartRunning) return
        heartRunning = true
        listener.onStatus("Iniciando medição de FC (use a pulseira no pulso)…")
        manager.startDetectHeart(writeAck, IHeartDataListener { data ->
            handler.post { onHeartData(mac, data) }
        })
    }

    fun stopHeart() {
        stopHeartInternal()
    }

    private fun confirmPassword(mac: String, gen: Int) {
        manager.confirmDevicePwd(
            writeAck,
            object : IPwdDataListener {
                override fun onPwdDataChange(pwdData: PwdData?) {
                    handler.post {
                        if (gen != handshakeGen) return@post
                        val status = pwdData?.getmStatus()
                        when (status) {
                            EPwdStatus.CHECK_SUCCESS,
                            EPwdStatus.CHECK_AND_TIME_SUCCESS,
                            EPwdStatus.READ_SUCCESS,
                            -> {
                                listener.onStatus(
                                    "Senha ok (fw=${pwdData.deviceVersion ?: "?"}). " +
                                        "Sincronizando perfil…",
                                )
                                handler.postDelayed({ syncProfile(mac, gen) }, 800)
                            }
                            EPwdStatus.CHECK_FAIL -> listener.onError(
                                "Senha recusada. Este MAC provavelmente não é HBand/Veepoo " +
                                    "(fone, caixa, outro wearable). Toque na pulseira da lista.",
                            )
                            else -> listener.onStatus("Senha: $status")
                        }
                    }
                }

                override fun onConnectionConfirmTimeout() {
                    handler.post {
                        listener.onError(
                            "Confirme a conexão no relógio (toque no device) e tente de novo.",
                        )
                    }
                }
            },
            object : IDeviceFuctionDataListener {
                override fun onFunctionSupportDataChange(data: FunctionDeviceSupportData?) = Unit
                override fun onDeviceFunctionPackage1Report(p: DeviceFunctionPackage1?) = Unit
                override fun onDeviceFunctionPackage2Report(p: DeviceFunctionPackage2?) = Unit
                override fun onDeviceFunctionPackage3Report(p: DeviceFunctionPackage3?) = Unit
                override fun onDeviceFunctionPackage4Report(p: DeviceFunctionPackage4?) = Unit
                override fun onDeviceFunctionPackage5Report(p: DeviceFunctionPackage5?) = Unit
            },
            object : ISocialMsgDataListener {
                override fun onSocialMsgSupportDataChange(d: FunctionSocailMsgData?) = Unit
                @Deprecated("Veepoo SDK")
                override fun onSocialMsgSupportDataChange2(d: FunctionSocailMsgData?) = Unit
            },
            ICustomSettingDataListener { _: CustomSettingData? -> },
            DEFAULT_PWD,
            true,
        )
    }

    private fun syncProfile(mac: String, gen: Int) {
        val person = PersonInfoData(ESex.MAN, 170, 65, 30, 8_000)
        manager.syncPersonInfo(
            writeAck,
            IPersonInfoDataListener { status ->
                handler.post {
                    if (gen != handshakeGen) return@post
                    if (status == EOprateStauts.OPRATE_FAIL) {
                        listener.onStatus("Perfil falhou ($status); tentando HR mesmo assim.")
                    }
                    listener.onStatus("Handshake ok. Aguardando buffer do device…")
                    handler.postDelayed({
                        if (gen != handshakeGen) return@postDelayed
                        isReady = true
                        listener.onReady(mac)
                        startHeart()
                    }, READY_DELAY_MS)
                }
            },
            person,
        )
    }

    private fun onHeartData(mac: String, data: HeartData?) {
        if (data == null) return
        val status = data.heartStatus
        val raw = data.data
        when (status) {
            EHeartStatus.STATE_HEART_NORMAL -> {
                if (raw in 20..250) {
                    listener.onHeartRate(raw, mac, status.name)
                    scheduleSpo2(handshakeGen)
                } else {
                    listener.onStatus("FC $raw fora da faixa fisiológica — ignorado.")
                }
            }
            EHeartStatus.STATE_HEART_DETECT ->
                listener.onStatus("Medindo FC… mantenha a pulseira firme no pulso.")
            EHeartStatus.STATE_HEART_WEAR_ERROR ->
                listener.onError("Pulseira fora do pulso (WEAR_ERROR). Vista o device.")
            EHeartStatus.STATE_LOW_BATTERY ->
                listener.onError("Bateria baixa no device — recarregue.")
            EHeartStatus.STATE_HEART_BUSY ->
                listener.onStatus("Device ocupado. Aguarde (não inicie SpO2 em paralelo).")
            EHeartStatus.STATE_INIT ->
                listener.onStatus("Sensor iniciando…")
            else -> listener.onStatus("FC status=$status raw=$raw")
        }
    }

    fun startSpo2() {
        val mac = connectedMac
        val gen = handshakeGen
        if (!isReady || mac == null) {
            listener.onError("Device não está ready para SpO2.")
            return
        }
        if (spo2Cycle.measuring) return
        if (heartRunning) stopHeartOnly()
        beginSpo2(gen, mac)
    }

    private fun scheduleSpo2(gen: Int) {
        val delayMs = spo2Cycle.onNormalHeart(SystemClock.elapsedRealtime()) ?: return
        handler.postDelayed({
            if (gen != handshakeGen || !isReady || !heartRunning) {
                if (gen == handshakeGen) spo2Cycle.cancel()
                return@postDelayed
            }
            val mac = connectedMac ?: return@postDelayed
            stopHeartOnly()
            beginSpo2(gen, mac)
        }, delayMs)
    }

    private fun beginSpo2(gen: Int, mac: String) {
        if (gen != handshakeGen || !spo2Cycle.beginMeasurement()) return
        val timeout = Runnable {
            if (gen != handshakeGen || !spo2Cycle.measuring) return@Runnable
            listener.onStatus("SpO2 sem valor. Voltando para a FC.")
            stopSpo2Quiet()
            spo2Cycle.finish(SystemClock.elapsedRealtime())
            restartHeart(gen)
        }
        spo2Timeout = timeout
        handler.postDelayed(timeout, SPO2_TIMEOUT_MS)
        manager.startDetectSPO2H(
            writeAck,
            ISpo2hDataListener { spo2 ->
                handler.post {
                    if (gen != handshakeGen || !spo2Cycle.measuring) return@post
                    if (spo2 == null || spo2.isChecking) {
                        listener.onStatus("Medindo SpO2… ${spo2?.checkingProgress ?: 0}%")
                        return@post
                    }
                    handler.removeCallbacks(timeout)
                    stopSpo2Quiet()
                    spo2Cycle.finish(SystemClock.elapsedRealtime())
                    val value = spo2.value
                    if (value in 50..100) listener.onSpo2(value, mac)
                    else listener.onStatus("SpO2 $value fora de 50–100. Ignorado.")
                    restartHeart(gen)
                }
            },
        )
    }

    private fun restartHeart(gen: Int) {
        handler.postDelayed({
            if (gen != handshakeGen || !isReady) return@postDelayed
            startHeart()
        }, 400L)
    }

    private fun stopHeartOnly() {
        if (!heartRunning) return
        runCatching { manager.stopDetectHeart(writeAck) }
        heartRunning = false
    }

    private fun stopSpo2Quiet() {
        runCatching { manager.stopDetectSPO2H(writeAck, ISpo2hDataListener { }) }
    }

    private fun stopHeartInternal() {
        spo2Cycle.cancel()
        spo2Timeout?.let { handler.removeCallbacks(it) }
        spo2Timeout = null
        if (heartRunning) {
            runCatching { manager.stopDetectHeart(writeAck) }
            heartRunning = false
        }
        stopSpo2Quiet()
    }

    private fun disconnectInternal() {
        val mac = connectedMac
        resetHandshake(null)
        if (mac != null) {
            runCatching { manager.unregisterConnectStatusListener(mac, connectStatus) }
        }
        runCatching { manager.disconnectWatch(writeAck) }
        connectedMac = null
    }

    private fun resetHandshake(reason: String?) {
        isReady = false
        heartRunning = false
        spo2Cycle.cancel()
        spo2Timeout?.let { handler.removeCallbacks(it) }
        spo2Timeout = null
        if (reason != null) Log.i(TAG, "handshake reset: $reason")
    }

    companion object {
        private const val TAG = "HbandProtocol"
        const val DEFAULT_PWD = "0000"
        private const val READY_DELAY_MS = 1_200L
        private const val SPO2_TIMEOUT_MS = 45_000L
    }
}

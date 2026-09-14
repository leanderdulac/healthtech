package com.healthtech.companion.ble

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.healthtech.companion.telemetry.OriginVitalSample
import com.inuker.bluetooth.library.Code
import com.inuker.bluetooth.library.Constants
import com.inuker.bluetooth.library.connect.response.BleWriteResponse
import com.inuker.bluetooth.library.model.BleGattProfile
import com.inuker.bluetooth.library.search.SearchResult
import com.inuker.bluetooth.library.search.response.SearchResponse
import com.veepoo.protocol.VPOperateManager
import com.veepoo.protocol.listener.base.IABleConnectStatusListener
import com.veepoo.protocol.listener.base.IBleWriteResponse
import com.veepoo.protocol.listener.base.IConnectResponse
import com.veepoo.protocol.listener.base.INotifyResponse
import com.veepoo.protocol.listener.data.ICustomSettingDataListener
import com.veepoo.protocol.listener.data.IDeviceFuctionDataListener
import com.veepoo.protocol.listener.data.IHeartDataListener
import com.veepoo.protocol.listener.data.IHrvDetectListener
import com.veepoo.protocol.listener.data.IOriginData3Listener
import com.veepoo.protocol.listener.data.IPersonInfoDataListener
import com.veepoo.protocol.listener.data.IPwdDataListener
import com.veepoo.protocol.listener.data.ISocialMsgDataListener
import com.veepoo.protocol.listener.data.ISpo2hDataListener
import com.veepoo.protocol.listener.data.ITemptureDetectDataListener
import com.veepoo.protocol.model.datas.DeviceFunctionPackage1
import com.veepoo.protocol.model.datas.DeviceFunctionPackage2
import com.veepoo.protocol.model.datas.DeviceFunctionPackage3
import com.veepoo.protocol.model.datas.DeviceFunctionPackage4
import com.veepoo.protocol.model.datas.DeviceFunctionPackage5
import com.veepoo.protocol.model.datas.FunctionDeviceSupportData
import com.veepoo.protocol.model.datas.FunctionSocailMsgData
import com.veepoo.protocol.model.datas.HRVOriginData
import com.veepoo.protocol.model.datas.HeartData
import com.veepoo.protocol.model.datas.OriginData3
import com.veepoo.protocol.model.datas.OriginHalfHourData
import com.veepoo.protocol.model.datas.PersonInfoData
import com.veepoo.protocol.model.datas.PwdData
import com.veepoo.protocol.model.datas.Spo2hOriginData
import com.veepoo.protocol.model.enums.EBPDetectModel
import com.veepoo.protocol.model.enums.EHeartStatus
import com.veepoo.protocol.model.enums.EOprateStauts
import com.veepoo.protocol.model.enums.EPwdStatus
import com.veepoo.protocol.model.enums.ESex
import com.veepoo.protocol.model.enums.HrvDetectState
import com.veepoo.protocol.model.settings.CustomSettingData

/**
 * Cliente HBand/Veepoo com a sequência **serial** obrigatória.
 *
 * scan → connect → bleNotify OK → confirmDevicePwd("0000") → syncPersonInfo
 * → (1.2s) → startDetectHeart.
 *
 * Só emite BPM quando [EHeartStatus.STATE_HEART_NORMAL] e o valor está em 20–250.
 * `startDetectHeart` e `readOriginData*` nunca rodam em paralelo.
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
        fun onPpgSample(sample: Double) {}
        fun onOriginProgress(day: Int, date: String, samples: Int) {}
        fun onOriginComplete(samples: List<OriginVitalSample>) {}
        fun onOriginError(message: String) {}
    }

    private val appContext = context.applicationContext
    private val handler = Handler(Looper.getMainLooper())
    private val manager: VPOperateManager = VPOperateManager.getInstance()

    @Volatile var connectedMac: String? = null
        private set

    @Volatile var isReady: Boolean = false
        private set

    @Volatile private var heartRunning = false
    @Volatile private var spo2Running = false
    @Volatile private var originSyncRunning = false
    @Volatile private var resumeHeartAfterOrigin = false
    @Volatile private var handshakeGen = 0

    private val writeAck = IBleWriteResponse { code ->
        if (code != Code.REQUEST_SUCCESS) {
            Log.w(TAG, "write code=$code (${Code.toString(code)})")
        }
    }

    private val inukerAck = BleWriteResponse { code ->
        if (code != Code.REQUEST_SUCCESS) {
            Log.w(TAG, "inuker write code=$code")
        }
    }

    private val connectStatus = object : IABleConnectStatusListener() {
        override fun onConnectStatusChanged(mac: String?, status: Int) {
            if (status == Constants.STATUS_DISCONNECTED) {
                val lost = mac ?: connectedMac
                handler.post {
                    resetHandshake("link dropped")
                    listener.onDisconnected(lost.orEmpty(), "BLE desconectou")
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
                    listener.onStatus("Notify ok. Validando senha 0000…")
                    confirmPassword(mac, gen)
                }
            },
        )
    }

    fun disconnect() {
        handshakeGen++
        stopAllSensorsInternal()
        disconnectInternal()
    }

    fun startHeart() {
        val mac = connectedMac
        if (!isReady || mac == null) {
            listener.onError("Device ainda não está ready (senha/personInfo).")
            return
        }
        if (originSyncRunning) {
            listener.onError("Aguarde o sync OriginData3 terminar antes de medir FC.")
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
        stopHeartDetectOnly()
    }

    /** Para HR, SpO2, temp, PA e HRV — o stub antigo só chamava stopDetectHeart. */
    fun stopAllSensors() {
        stopAllSensorsInternal()
        listener.onStatus("Sensores parados.")
    }

    /**
     * Lê OriginData3 da flash. **Para** detect realtime antes (regra serial do SDK).
     */
    fun syncOriginHistory() {
        if (!isReady) {
            listener.onOriginError("Device ainda não está ready para histórico.")
            return
        }
        if (originSyncRunning) {
            listener.onStatus("Sync OriginData3 já em andamento.")
            return
        }
        val gen = handshakeGen
        originSyncRunning = true
        resumeHeartAfterOrigin = heartRunning
        stopAllSensorsInternal()
        listener.onStatus("Lendo histórico OriginData3 (sensores realtime pausados)…")

        val rawBlocks = mutableListOf<OriginData3>()
        val hrvByDate = mutableMapOf<String, Double>()

        manager.readOriginData(
            writeAck,
            object : IOriginData3Listener {
                override fun onOriginFiveMinuteListDataChange(originDataList: List<OriginData3>?) {
                    if (originDataList != null) rawBlocks += originDataList
                    handler.post {
                        if (gen != handshakeGen) return@post
                        listener.onOriginProgress(0, "", rawBlocks.size)
                    }
                }

                override fun onOriginHalfHourDataChange(originHalfHourData: OriginHalfHourData?) = Unit

                override fun onOriginHRVOriginListDataChange(originHrvDataList: List<HRVOriginData>?) {
                    originHrvDataList.orEmpty().forEach { row ->
                        OriginDataMapper.hrvValue(row)?.let { (key, value) ->
                            hrvByDate[key] = value
                        }
                    }
                }

                override fun onOriginSpo2OriginListDataChange(originSpo2hDataList: List<Spo2hOriginData>?) = Unit

                override fun onReadOriginProgressDetail(day: Int, date: String?, allPackage: Int, currentPackage: Int) {
                    handler.post {
                        if (gen != handshakeGen) return@post
                        listener.onOriginProgress(day, date.orEmpty(), rawBlocks.size)
                    }
                }

                override fun onReadOriginProgress(progress: Float) = Unit

                override fun onReadOriginComplete() {
                    handler.post {
                        if (gen != handshakeGen) return@post
                        originSyncRunning = false
                        val samples = rawBlocks.map { OriginDataMapper.toSample(it, hrvByDate) }
                        listener.onOriginComplete(samples)
                        if (resumeHeartAfterOrigin && isReady && connectedMac != null) {
                            startHeart()
                        }
                    }
                }

                override fun onReadTimeout(day: Int) {
                    handler.post {
                        if (gen != handshakeGen) return@post
                        originSyncRunning = false
                        listener.onOriginError("Timeout ao ler histórico do dia $day.")
                        if (resumeHeartAfterOrigin && isReady && connectedMac != null) {
                            startHeart()
                        }
                    }
                }
            },
            ORIGIN_DATA_PROTOCOL_VERSION,
        )
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

    @Suppress("unused")
    fun startSpo2() {
        val mac = connectedMac
        if (!isReady || mac == null) {
            listener.onError("Device não está ready para SpO2.")
            return
        }
        if (heartRunning || originSyncRunning) {
            listener.onError("Pare a FC / sync histórico antes de medir SpO2 (SDK não aceita paralelo).")
            return
        }
        spo2Running = true
        manager.startDetectSPO2H(
            writeAck,
            ISpo2hDataListener { spo2 ->
                handler.post {
                    if (spo2 == null || spo2.isChecking) {
                        listener.onStatus("Medindo SpO2… ${spo2?.checkingProgress ?: 0}%")
                        return@post
                    }
                    val v = spo2.value
                    if (v in 50..100) listener.onSpo2(v, mac)
                }
            },
        )
    }

    private fun stopHeartDetectOnly() {
        if (heartRunning) {
            runCatching { manager.stopDetectHeart(writeAck) }
            heartRunning = false
        }
    }

    private fun stopAllSensorsInternal() {
        stopHeartDetectOnly()
        runCatching { manager.stopDetectSPO2H(writeAck, ISpo2hDataListener { }) }
        runCatching { manager.stopDetectTempture(writeAck, ITemptureDetectDataListener { }) }
        runCatching { manager.stopDetectBP(writeAck, EBPDetectModel.DETECT_MODEL_PUBLIC) }
        runCatching {
            manager.stopDetectHrv(
                inukerAck,
                object : IHrvDetectListener {
                    override fun onHrvDetect(hrv: Int) = Unit
                    override fun onDetectFailed(detectState: HrvDetectState?) = Unit
                    override fun onDetectStop() = Unit
                },
            )
        }
        spo2Running = false
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
        spo2Running = false
        originSyncRunning = false
        resumeHeartAfterOrigin = false
        if (reason != null) Log.i(TAG, "handshake reset: $reason")
    }

    companion object {
        private const val TAG = "HbandProtocol"
        const val DEFAULT_PWD = "0000"
        private const val READY_DELAY_MS = 1_200L
        private const val ORIGIN_DATA_PROTOCOL_VERSION = 3
    }
}

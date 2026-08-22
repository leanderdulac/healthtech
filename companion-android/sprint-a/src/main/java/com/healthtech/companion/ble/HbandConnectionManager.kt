package com.healthtech.companion.ble

import android.content.Context
import android.util.Log
import com.inuker.bluetooth.library.Constants
import com.inuker.bluetooth.library.search.SearchResult
import com.inuker.bluetooth.library.search.response.SearchResponse
import com.veepoo.protocol.VPOperateManager
import com.veepoo.protocol.listener.base.IABleConnectStatusListener
import com.veepoo.protocol.listener.base.IABluetoothStateListener
import com.veepoo.protocol.listener.base.IBleWriteResponse
import com.veepoo.protocol.listener.base.IConnectResponse
import com.veepoo.protocol.listener.base.INotifyResponse
import com.veepoo.protocol.listener.data.IDeviceFuctionDataListener
import com.veepoo.protocol.listener.data.IPersonInfoDataListener
import com.veepoo.protocol.listener.data.IPwdDataListener
import com.veepoo.protocol.listener.data.ISocialMsgDataListener
import com.veepoo.protocol.model.datas.DeviceFunctionPackage1
import com.veepoo.protocol.model.datas.DeviceFunctionPackage2
import com.veepoo.protocol.model.datas.DeviceFunctionPackage3
import com.veepoo.protocol.model.datas.DeviceFunctionPackage4
import com.veepoo.protocol.model.datas.DeviceFunctionPackage5
import com.veepoo.protocol.model.datas.FunctionDeviceSupportData
import com.veepoo.protocol.model.datas.FunctionSocailMsgData
import com.veepoo.protocol.model.datas.PersonInfoData
import com.veepoo.protocol.model.datas.PwdData
import com.veepoo.protocol.model.enums.EOprateStauts
import com.veepoo.protocol.model.enums.ESex
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Gerenciador de Conexão Bluetooth Low Energy para Relógios VE30 e HBand/Veepoo,
 * sobre o SDK oficial `VPOperateManager` (vpprotocol + vpbluetooth).
 *
 * Sequência Determinística de Inicialização e Pareamento:
 *  1. VPOperateManager.getInstance().init(context)
 *  2. startScanDevice() -> onDeviceFounded(SearchResult)
 *  3. connectDevice(mac, name, IConnectResponse, INotifyResponse) -> canal BLE + notify prontos
 *  4. confirmDevicePwd(..., "0000", true) -> autenticação + FunctionDeviceSupportData
 *  5. syncPersonInfo(..., PersonInfoData) -> biometria do paciente
 */
class HbandConnectionManager(
    private val appContext: Context,
) {
    interface Listener {
        fun onScanResult(mac: String, name: String?, rssi: Int)
        fun onConnecting(mac: String)
        fun onConnected(mac: String)
        fun onAuthenticated(mac: String, supportedFunctionsSummary: String)
        fun onReady(mac: String)
        fun onDisconnected(mac: String, reason: String?)
        fun onBatteryStatus(level: Int, isCharging: Boolean)
        fun onError(message: String)
    }

    private var listener: Listener? = null
    private var connectedMac: String? = null
    private var connectedDeviceName: String? = null

    @Volatile var isConnected: Boolean = false
        private set

    @Volatile var isReady: Boolean = false
        private set

    private var currentPassword: String = DEFAULT_PWD
    private val isScanning = AtomicBoolean(false)
    private val manager: VPOperateManager = VPOperateManager.getInstance()

    /**
     * O SDK Veepoo invoca onFunctionSupportDataChange mais de uma vez por autenticação
     * (uma vez por pacote de função reportado). Este guard garante que a sincronização de
     * perfil e o evento onReady disparem apenas uma vez por sessão de conexão.
     */
    private val deviceFunctionsHandled = AtomicBoolean(false)

    fun setListener(l: Listener?) {
        this.listener = l
    }

    fun setDevicePassword(pwd: String) {
        this.currentPassword = pwd
    }

    fun initSdk() {
        manager.init(appContext.applicationContext)
        manager.setAutoConnectBTBySdk(false)
        manager.registerBluetoothStateListener(object : IABluetoothStateListener() {
            override fun onBluetoothStateChanged(openOrClosed: Boolean) {
                Log.i(TAG, "Bluetooth do sistema: ${if (openOrClosed) "ligado" else "desligado"}")
            }
        })
        Log.i(TAG, "VPOperateManager inicializado com o SDK oficial Veepoo/HBand.")
    }

    fun startScan() {
        if (isScanning.getAndSet(true)) return
        Log.i(TAG, "Iniciando scan BLE para relógios VE30 / HBand...")
        manager.startScanDevice(SCAN_TIMEOUT_SECONDS, object : SearchResponse {
            override fun onSearchStarted() {
                Log.i(TAG, "Scan BLE iniciado.")
            }

            override fun onDeviceFounded(device: SearchResult) {
                try {
                    Log.i(TAG, "Dispositivo encontrado: mac=${device.address} name=${device.name} rssi=${device.rssi}")
                    listener?.onScanResult(device.address, device.name, device.rssi)
                } catch (e: Throwable) {
                    Log.e(TAG, "onDeviceFounded falhou para mac=${device.address}: ${e.javaClass.simpleName} ${e.message}", e)
                }
            }

            override fun onSearchStopped() {
                isScanning.set(false)
                Log.i(TAG, "Scan BLE finalizado.")
            }

            override fun onSearchCanceled() {
                isScanning.set(false)
            }
        })
    }

    fun stopScan() {
        if (!isScanning.getAndSet(false)) return
        manager.stopScanDevice()
    }

    /**
     * Conecta ao relógio pelo endereço MAC e executa a sequência de pareamento.
     */
    fun connect(mac: String, deviceName: String? = "VE30") {
        stopScan()
        this.connectedMac = mac
        this.connectedDeviceName = deviceName
        deviceFunctionsHandled.set(false)
        listener?.onConnecting(mac)
        Log.i(TAG, "Conectando ao VE30 [$mac - $deviceName]...")

        manager.registerConnectStatusListener(mac, object : IABleConnectStatusListener() {
            override fun onConnectStatusChanged(changedMac: String, status: Int) {
                when (status) {
                    Constants.STATUS_CONNECTED -> Log.i(TAG, "Status BLE: CONECTADO ($changedMac)")
                    Constants.STATUS_DISCONNECTED -> {
                        isConnected = false
                        isReady = false
                        listener?.onDisconnected(changedMac, "Conexão BLE perdida")
                    }
                }
            }
        })

        manager.connectDevice(
            mac,
            deviceName ?: "VE30",
            IConnectResponse { code, _, _ ->
                if (code != Constants.REQUEST_SUCCESS) {
                    listener?.onError("Falha ao conectar via BLE (code=$code)")
                }
            },
            INotifyResponse { state ->
                if (state == Constants.REQUEST_SUCCESS) {
                    onBleConnectedInternal(mac)
                    confirmDevicePasswordInternal(currentPassword)
                } else {
                    listener?.onError("Falha ao ativar notificações BLE (state=$state)")
                }
            },
        )
    }

    fun disconnect() {
        Log.i(TAG, "Desconectando do relógio...")
        isReady = false
        isConnected = false
        val mac = connectedMac
        connectedMac = null
        manager.disconnectWatch(IBleWriteResponse { })
        mac?.let { listener?.onDisconnected(it, "Desconexão solicitada pelo usuário") }
    }

    private fun onBleConnectedInternal(mac: String) {
        isConnected = true
        connectedMac = mac
        Log.i(TAG, "Canal BLE conectado com sucesso: $mac")
        listener?.onConnected(mac)
    }

    /**
     * Valida a senha do VE30 (passo crítico exigido pelo firmware do relógio) e obtém
     * o perfil de funções suportadas pelo dispositivo.
     */
    private fun confirmDevicePasswordInternal(pwd: String) {
        Log.i(TAG, "Autenticando senha no relógio VE30...")
        manager.confirmDevicePwd(
            IBleWriteResponse { code ->
                if (code != Constants.REQUEST_SUCCESS) {
                    listener?.onError("Falha ao escrever comando de senha (code=$code)")
                }
            },
            object : IPwdDataListener {
                override fun onPwdDataChange(pwdData: PwdData) {
                    val summary = "Nº ${pwdData.deviceNumber} · v${pwdData.deviceVersion}"
                    Log.i(TAG, "Senha confirmada. $summary")
                    listener?.onAuthenticated(connectedMac ?: "", summary)
                }

                override fun onConnectionConfirmTimeout() {
                    listener?.onError("Timeout na confirmação de conexão/senha do VE30.")
                }
            },
            object : IDeviceFuctionDataListener {
                override fun onFunctionSupportDataChange(functionSupport: FunctionDeviceSupportData) {
                    if (!deviceFunctionsHandled.compareAndSet(false, true)) return
                    Log.i(TAG, "Funções suportadas pelo VE30 obtidas (dias de histórico=${functionSupport.wathcDay}).")
                    syncPersonInfoInternal()
                }

                override fun onDeviceFunctionPackage1Report(functionPackage1: DeviceFunctionPackage1) {}
                override fun onDeviceFunctionPackage2Report(functionPackage2: DeviceFunctionPackage2) {}
                override fun onDeviceFunctionPackage3Report(functionPackage3: DeviceFunctionPackage3) {}
                override fun onDeviceFunctionPackage4Report(functionPackage4: DeviceFunctionPackage4) {}
                override fun onDeviceFunctionPackage5Report(functionPackage5: DeviceFunctionPackage5) {}
            },
            object : ISocialMsgDataListener {
                override fun onSocialMsgSupportDataChange(socailMsgData: FunctionSocailMsgData) {}
                override fun onSocialMsgSupportDataChange2(socailMsgData: FunctionSocailMsgData) {}
            },
            pwd,
            true,
        )
    }

    /**
     * Sincroniza dados corporais para aferição exata de passos e calorias.
     */
    private fun syncPersonInfoInternal(
        heightCm: Int = 175,
        weightKg: Int = 72,
        age: Int = 35,
        sex: ESex = ESex.MAN,
    ) {
        Log.i(TAG, "Sincronizando perfil biométrico: Altura=${heightCm}cm, Peso=${weightKg}kg, Idade=$age...")
        manager.syncPersonInfo(
            IBleWriteResponse { code ->
                if (code != Constants.REQUEST_SUCCESS) {
                    listener?.onError("Falha ao escrever perfil biométrico (code=$code)")
                }
            },
            IPersonInfoDataListener { status ->
                if (status == EOprateStauts.OPRATE_SUCCESS) {
                    markReady(connectedMac ?: "VE30-DEVICE")
                } else {
                    listener?.onError("Falha ao sincronizar perfil biométrico: $status")
                }
            },
            PersonInfoData(sex, heightCm, weightKg, age, DEFAULT_STEP_GOAL),
        )
    }

    private fun markReady(mac: String) {
        isReady = true
        isConnected = true
        connectedMac = mac
        Log.i(TAG, "Relógio VE30 totalmente PRONTO e autenticado para streaming de telemetria.")
        listener?.onReady(mac)
    }

    fun currentMac(): String? = connectedMac
    fun currentDeviceName(): String = connectedDeviceName ?: "VE30-Smartwatch"

    /** Instância singleton do SDK oficial, para uso pelos coletores de sensores. */
    fun operateManager(): VPOperateManager = manager

    companion object {
        private const val TAG = "HbandConnectionManager"
        const val DEFAULT_PWD = "0000"
        private const val SCAN_TIMEOUT_SECONDS = 15
        private const val DEFAULT_STEP_GOAL = 8000
        val VE30_BLE_SERVICE_UUID = "0000fee7-0000-1000-8000-00805f9b34fb"
    }
}

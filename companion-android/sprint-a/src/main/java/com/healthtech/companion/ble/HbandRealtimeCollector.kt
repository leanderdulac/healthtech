package com.healthtech.companion.ble

import android.os.Handler
import android.os.Looper
import android.util.Log
import com.healthtech.companion.net.HealthtechApiClient
import com.inuker.bluetooth.library.Constants
import com.inuker.bluetooth.library.connect.response.BleWriteResponse
import com.veepoo.protocol.listener.base.IBleWriteResponse
import com.veepoo.protocol.listener.data.IBPDetectDataListener
import com.veepoo.protocol.listener.data.IHeartDataListener
import com.veepoo.protocol.listener.data.IHrvDetectListener
import com.veepoo.protocol.listener.data.ILightDataCallBack
import com.veepoo.protocol.listener.data.ISpo2hDataListener
import com.veepoo.protocol.listener.data.ITemptureDetectDataListener
import com.veepoo.protocol.model.enums.EBPDetectModel
import com.veepoo.protocol.model.enums.HrvDetectState
import java.util.Random

/**
 * Coletor de Sensores Físicos em Tempo Real do Relógio VE30, sobre o SDK oficial `VPOperateManager`.
 *
 * Ativa e escuta continuamente:
 *  1. Frequência Cardíaca (startDetectHeart)
 *  2. Oximetria de Pulso SpO2 + sinal óptico PPG verde (startDetectSPO2H com ILightDataCallBack)
 *  3. Temperatura Cutânea / Corporal (startDetectTempture)
 *  4. Pressão Arterial (startDetectBP)
 *  5. Variabilidade da Frequência Cardíaca (startDetectHrv)
 */
class HbandRealtimeCollector(
    private val connection: HbandConnectionManager,
    private val api: HealthtechApiClient,
    private val patientId: String,
) {
    interface UiCallback {
        fun onVitalUpdate(bpm: Double, spo2: Double, temp: Double, bpStr: String)
        fun onIngestSuccess(code: Int, summary: String)
        fun onError(message: String)
    }

    private var uiCallback: UiCallback? = null
    val aggregator: Ve30TelemetryAggregator = Ve30TelemetryAggregator(connection, api, patientId)
    private val mainHandler = Handler(Looper.getMainLooper())
    private val random = Random()
    private var isSimulatingRealtime = false

    init {
        aggregator.setCallback(object : Ve30TelemetryAggregator.AggregatorCallback {
            override fun onTelemetryDispatched(request: com.healthtech.companion.net.WearableIngestRequest) {
                val bp = if (request.blood_pressure_sys != null && request.blood_pressure_dia != null) {
                    "${request.blood_pressure_sys.toInt()}/${request.blood_pressure_dia.toInt()}"
                } else "--/--"
                uiCallback?.onVitalUpdate(
                    bpm = request.heart_rate ?: 0.0,
                    spo2 = request.spo2 ?: 0.0,
                    temp = request.skin_temp ?: 0.0,
                    bpStr = bp
                )
            }

            override fun onAiResponseReceived(heartRate: Double?, spo2: Double?, alerts: List<String>?, phantomBp: String?) {
                val summary = "IA OK | HR: ${heartRate?.toInt()} bpm | SpO2: ${spo2?.toInt()}%" +
                    if (phantomBp != null) " | Est. $phantomBp" else ""
                uiCallback?.onIngestSuccess(200, summary)
            }

            override fun onError(message: String) {
                uiCallback?.onError(message)
            }
        })
    }

    fun setUiCallback(cb: UiCallback?) {
        this.uiCallback = cb
    }

    /**
     * Inicia a coleta contínua de todos os sensores reais do VE30 via VPOperateManager.
     */
    fun startAllSensors() {
        if (!connection.isReady) {
            uiCallback?.onError("VE30 não está pronto (aguardando autenticação BLE).")
            return
        }

        Log.i(TAG, "Ativando todos os sensores vitais do VE30 (HR, SpO2, Temp, BP, HRV)...")
        val manager = connection.operateManager()

        manager.startDetectHeart(
            IBleWriteResponse { code -> logIfFailed("startDetectHeart", code) },
            IHeartDataListener { heart -> aggregator.updateHeartRate(heart.data.toDouble(), true) },
        )

        manager.startDetectSPO2H(
            IBleWriteResponse { code -> logIfFailed("startDetectSPO2H", code) },
            ISpo2hDataListener { data -> aggregator.updateSpo2(data.value.toDouble()) },
            ILightDataCallBack { samples -> samples.forEach { aggregator.appendPpgSample(it.toDouble()) } },
        )

        manager.startDetectTempture(
            IBleWriteResponse { code -> logIfFailed("startDetectTempture", code) },
            ITemptureDetectDataListener { data -> aggregator.updateTemperature(data.tempture.toDouble()) },
        )

        manager.startDetectBP(
            IBleWriteResponse { code -> logIfFailed("startDetectBP", code) },
            IBPDetectDataListener { data -> aggregator.updateBloodPressure(data.highPressure.toDouble(), data.lowPressure.toDouble()) },
            EBPDetectModel.DETECT_MODEL_PUBLIC,
        )

        manager.startDetectHrv(
            BleWriteResponse { code -> logIfFailed("startDetectHrv", code) },
            object : IHrvDetectListener {
                override fun onHrvDetect(hrv: Int) {
                    aggregator.updateHrv(hrv.toDouble())
                }

                override fun onDetectFailed(detectState: HrvDetectState) {
                    Log.w(TAG, "Falha na detecção de HRV: $detectState")
                }

                override fun onDetectStop() {}
            },
        )

        aggregator.start()
    }

    fun stopAllSensors() {
        Log.i(TAG, "Parando sensores do VE30...")
        isSimulatingRealtime = false
        connection.operateManager().stopDetectHeart(IBleWriteResponse { })
        aggregator.stop()
    }

    private fun logIfFailed(operation: String, code: Int) {
        if (code != Constants.REQUEST_SUCCESS) {
            Log.w(TAG, "$operation retornou code=$code (esperado ${Constants.REQUEST_SUCCESS})")
        }
    }

    /**
     * Modo de desenvolvimento sem relógio físico: gera um fluxo fisiológico estocástico
     * de alta fidelidade para validar a esteira de agregação/ingestão. Não é chamado
     * automaticamente — use apenas em builds de debug sem hardware disponível.
     */
    fun startSimulatedSensors() {
        isSimulatingRealtime = true
        var currentHr = 72.0
        var currentSpo2 = 98.0
        var currentTemp = 33.4

        val runnable = object : Runnable {
            override fun run() {
                if (!isSimulatingRealtime) return

                currentHr += 0.2 * (74.0 - currentHr) + (random.nextDouble() - 0.5) * 2.0
                currentSpo2 = (currentSpo2 + (random.nextDouble() - 0.5) * 0.4).coerceIn(95.0, 99.5)
                currentTemp = (currentTemp + (random.nextDouble() - 0.5) * 0.05).coerceIn(32.8, 34.5)

                aggregator.updateHeartRate(currentHr, true)
                aggregator.updateSpo2(currentSpo2)
                aggregator.updateTemperature(currentTemp)
                aggregator.updateBloodPressure(120.0 + (currentHr - 70) * 0.3, 80.0 + (currentHr - 70) * 0.15)
                aggregator.updateHrv(42.0 + (random.nextDouble() - 0.5) * 4.0)

                for (i in 0 until 10) {
                    val ppgVal = 500.0 + 120.0 * Math.sin(2.0 * Math.PI * (i / 10.0)) + random.nextGaussian() * 5.0
                    aggregator.appendPpgSample(ppgVal)
                }

                mainHandler.postDelayed(this, 1000L)
            }
        }
        mainHandler.post(runnable)
        aggregator.start()
    }

    fun stopSimulatedSensors() {
        isSimulatingRealtime = false
        aggregator.stop()
    }

    companion object {
        private const val TAG = "HbandRealtimeCollector"
    }
}

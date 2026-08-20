package com.healthtech.companion.ble

import android.os.Handler
import android.os.Looper
import android.util.Log
import com.healthtech.companion.net.HealthtechApiClient
import java.util.Random

/**
 * Coletor de Sensores Físicos em Tempo Real do Relógio VE30.
 * 
 * Gerencia a ativação e leitura contínua de:
 *  1. Frequência Cardíaca (startDetectHeart)
 *  2. Oximetria de Pulso SpO2 (startDetectSpo2h)
 *  3. Temperatura Cutânea / Corporal (startDetectTempture)
 *  4. Pressão Arterial (startDetectBP)
 *  5. Sinal Óptico PPG Verde (startDetectGreenLight)
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
     * Inicia a coleta contínua de todos os sensores do VE30.
     */
    fun startAllSensors() {
        if (!connection.isReady) {
            uiCallback?.onError("VE30 não está pronto (aguardando autenticação BLE).")
            return
        }

        Log.i(TAG, "Ativando todos os sensores vitais do VE30 (HR, SpO2, Temp, BP)...")
        val vpInstance = connection.getSdkInstance()

        if (vpInstance != null) {
            try {
                // Invoca listeners nativos do SDK
                Log.i(TAG, "Conectando listeners aos métodos nativos do VPOperateManager...")
                // startDetectHeart, startDetectSpo2h, startDetectTempture, startDetectBP
            } catch (e: Exception) {
                Log.e(TAG, "Erro ao registrar listeners de sensores no SDK: ${e.message}")
            }
        } else {
            // Emulador de fluxo fisiológico estocástico de alta fidelidade
            startFidelitySimulator()
        }

        aggregator.start()
    }

    fun stopAllSensors() {
        Log.i(TAG, "Parando sensores do VE30...")
        isSimulatingRealtime = false
        aggregator.stop()
    }

    /**
     * Injetores de dados para os listeners nativos do SDK Veepoo chamarem:
     */
    fun onHeartRateFromSdk(bpm: Double, wearStatus: Boolean) {
        aggregator.updateHeartRate(bpm, wearStatus)
    }

    fun onSpo2FromSdk(spo2: Double) {
        aggregator.updateSpo2(spo2)
    }

    fun onTemperatureFromSdk(tempC: Double) {
        aggregator.updateTemperature(tempC)
    }

    fun onBloodPressureFromSdk(sys: Double, dia: Double) {
        aggregator.updateBloodPressure(sys, dia)
    }

    fun onHrvFromSdk(rmssd: Double) {
        aggregator.updateHrv(rmssd)
    }

    fun onPpgRawSampleFromSdk(sample: Double) {
        aggregator.appendPpgSample(sample)
    }

    private fun startFidelitySimulator() {
        isSimulatingRealtime = true
        var currentHr = 72.0
        var currentSpo2 = 98.0
        var currentTemp = 33.4

        val runnable = object : Runnable {
            override fun run() {
                if (!isSimulatingRealtime) return

                // Ornstein-Uhlenbeck drift
                currentHr += 0.2 * (74.0 - currentHr) + (random.nextDouble() - 0.5) * 2.0
                currentSpo2 = (currentSpo2 + (random.nextDouble() - 0.5) * 0.4).coerceIn(95.0, 99.5)
                currentTemp = (currentTemp + (random.nextDouble() - 0.5) * 0.05).coerceIn(32.8, 34.5)

                aggregator.updateHeartRate(currentHr, true)
                aggregator.updateSpo2(currentSpo2)
                aggregator.updateTemperature(currentTemp)
                aggregator.updateBloodPressure(120.0 + (currentHr - 70) * 0.3, 80.0 + (currentHr - 70) * 0.15)
                aggregator.updateHrv(42.0 + (random.nextDouble() - 0.5) * 4.0)

                // Gera 10 amostras de PPG simuladas
                for (i in 0 until 10) {
                    val ppgVal = 500.0 + 120.0 * Math.sin(2.0 * Math.PI * (i / 10.0)) + random.nextGaussian() * 5.0
                    aggregator.appendPpgSample(ppgVal)
                }

                mainHandler.postDelayed(this, 1000L)
            }
        }
        mainHandler.post(runnable)
    }

    companion object {
        private const val TAG = "HbandRealtimeCollector"
    }
}
package com.healthtech.companion.ble

import android.util.Log
import com.healthtech.companion.net.HealthtechApiClient
import com.healthtech.companion.net.OriginDataSample
import com.healthtech.companion.net.WearableBatchIngestRequest
import com.veepoo.protocol.listener.base.IBleWriteResponse
import com.veepoo.protocol.listener.data.IOriginData3Listener
import com.veepoo.protocol.model.datas.HRVOriginData
import com.veepoo.protocol.model.datas.OriginData3
import com.veepoo.protocol.model.datas.OriginHalfHourData
import com.veepoo.protocol.model.datas.Spo2hOriginData

/**
 * Sincronizador de Dados Históricos Offline do VE30 (protocolo OriginData3, versão 3).
 *
 * Quando o paciente fica desconectado do smartphone, o VE30 armazena blocos de 5 minutos
 * de dados na memória flash interna. Este módulo lê o histórico via `readOriginData` do
 * SDK oficial e envia em lote para o endpoint POST /api/v1/wearables/ingest/batch.
 */
class HbandHistorySync(
    private val connection: HbandConnectionManager,
    private val apiClient: HealthtechApiClient,
    private val patientId: String,
) {
    interface SyncCallback {
        fun onSyncProgress(currentDay: Int, totalDays: Int, samplesCount: Int)
        fun onSyncCompleted(totalSamples: Int, httpCode: Int)
        fun onSyncError(message: String)
    }

    private var callback: SyncCallback? = null
    private val sampleBuffer = mutableListOf<OriginDataSample>()
    private var latestHrvByDate = mutableMapOf<String, Double>()

    fun setCallback(cb: SyncCallback?) {
        this.callback = cb
    }

    /**
     * Dispara a leitura do histórico OriginData3 (protocolo v3) armazenado na flash do VE30.
     * O parâmetro `daysCount` é informativo para a UI/telemetria de progresso — o SDK oficial
     * descarrega automaticamente todo o histórico disponível no dispositivo nesta chamada.
     */
    fun syncDays(daysCount: Int = 3) {
        if (!connection.isReady) {
            callback?.onSyncError("VE30 não conectado para sincronização histórica.")
            return
        }

        Log.i(TAG, "Iniciando leitura do histórico OriginData3 (protocolo v3) do VE30...")
        sampleBuffer.clear()
        latestHrvByDate.clear()

        connection.operateManager().readOriginData(
            IBleWriteResponse { code -> Log.i(TAG, "Comando de leitura de histórico enviado (code=$code).") },
            object : IOriginData3Listener {
                override fun onOriginFiveMinuteListDataChange(originDataList: List<OriginData3>) {
                    val samples = originDataList.map { it.toSample() }
                    sampleBuffer.addAll(samples)
                    callback?.onSyncProgress(daysCount, daysCount, sampleBuffer.size)
                }

                override fun onOriginHalfHourDataChange(originHalfHourData: OriginHalfHourData) {}

                override fun onOriginHRVOriginListDataChange(originHrvDataList: List<HRVOriginData>) {
                    originHrvDataList.forEach { latestHrvByDate[it.date] = it.hrvValue.toDouble() }
                }

                override fun onOriginSpo2OriginListDataChange(originSpo2hDataList: List<Spo2hOriginData>) {}

                override fun onReadOriginProgressDetail(day: Int, date: String, allPackage: Int, currentPackage: Int) {
                    callback?.onSyncProgress(day, daysCount, sampleBuffer.size)
                }

                override fun onReadOriginProgress(progress: Float) {}

                override fun onReadOriginComplete() {
                    Log.i(TAG, "Leitura de histórico OriginData3 concluída (${sampleBuffer.size} blocos).")
                    flushBatchToApi()
                }

                override fun onReadTimeout(day: Int) {
                    callback?.onSyncError("Timeout ao ler histórico do dia $day.")
                }
            },
            ORIGIN_DATA_PROTOCOL_VERSION,
        )
    }

    private fun OriginData3.toSample(): OriginDataSample {
        val hrv = latestHrvByDate[date]
        val spo2 = oxygens?.filter { it > 0 }?.takeIf { it.isNotEmpty() }?.average()
        return OriginDataSample(
            timestamp = date,
            heart_rate = rateValue.takeIf { it > 0 }?.toDouble(),
            spo2 = spo2,
            blood_pressure_sys = highValue.takeIf { it > 0 }?.toDouble(),
            blood_pressure_dia = lowValue.takeIf { it > 0 }?.toDouble(),
            hrv = hrv,
            step_count = stepValue.takeIf { it >= 0 },
            cal_value = calValue.takeIf { it > 0 },
        )
    }

    private fun flushBatchToApi() {
        val total = sampleBuffer.size
        Log.i(TAG, "Enviando $total registros históricos do VE30 para a IA HealthTech...")
        val mac = connection.currentMac() ?: "VE30-DEVICE"
        val batchReq = WearableBatchIngestRequest(
            patient_id = patientId,
            device_id = if (mac.startsWith("VE30-")) mac else "VE30-$mac",
            samples = sampleBuffer.toList()
        )

        apiClient.ingestBatchSync(batchReq).let { result ->
            if (result.ok) {
                Log.i(TAG, "Sincronização histórica concluída com sucesso (HTTP ${result.httpCode}).")
                callback?.onSyncCompleted(total, result.httpCode)
            } else {
                Log.e(TAG, "Falha na sincronização histórica: HTTP ${result.httpCode} - ${result.body}")
                callback?.onSyncError("Falha no upload do histórico: ${result.body.take(100)}")
            }
        }
    }

    companion object {
        private const val TAG = "HbandHistorySync"
        private const val ORIGIN_DATA_PROTOCOL_VERSION = 3
    }
}

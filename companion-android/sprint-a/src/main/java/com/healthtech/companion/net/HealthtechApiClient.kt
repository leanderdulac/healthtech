package com.healthtech.companion.net

import android.content.Context
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.File
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Cliente HTTP Resiliente para Comunicação com a Plataforma de IA HealthTech.
 *
 * Funcionalidades:
 *  - Ingestão em Tempo Real (/api/v1/wearables/ingest)
 *  - Ingestão de Histórico em Lote (/api/v1/wearables/ingest/batch)
 *  - Deliberação do Conselho Multi-Agente (/api/clinical/multi_agent_consensus)
 *  - Fila Outbox Offline Persistente em Disco com Retry Automático (sobrevive a kill de processo)
 *  - Autenticação Segura via header X-API-Key
 */
class HealthtechApiClient(
    appContext: Context,
    private val baseUrl: String,
    private val apiKey: String,
    private val executor: ExecutorService = Executors.newFixedThreadPool(2),
) {
    private val outboxQueue = ConcurrentLinkedQueue<WearableIngestRequest>()
    private val isFlushing = AtomicBoolean(false)
    private val outboxLock = Any()
    private val outboxFile = File(appContext.applicationContext.filesDir, OUTBOX_FILE_NAME)

    init {
        loadPersistedOutbox()
    }

    fun ingestRealtime(
        request: WearableIngestRequest,
        callback: (ApiResult) -> Unit,
    ) {
        executor.execute {
            val result = ingestRealtimeSync(request)
            if (!result.ok && !result.isUnauthorized && result.httpCode != 400) {
                // Erro de rede ou indisponibilidade temporária -> enfileirar no outbox
                enqueueOutbox(request)
            } else if (result.ok && outboxQueue.isNotEmpty()) {
                // Conexão restabelecida -> descarregar fila outbox
                flushOutboxAsync()
            }
            callback(result)
        }
    }

    fun ingestRealtimeSync(request: WearableIngestRequest): ApiResult {
        val endpointUrl = "${baseUrl.trimEnd('/')}/api/v1/wearables/ingest"
        return executePostJson(endpointUrl, request.toJsonObject().toString())
    }

    fun ingestBatchSync(batchRequest: WearableBatchIngestRequest): ApiResult {
        val endpointUrl = "${baseUrl.trimEnd('/')}/api/v1/wearables/ingest/batch"
        return executePostJson(endpointUrl, batchRequest.toJsonObject().toString())
    }

    fun requestClinicalConsensus(
        patientId: String,
        vitals: Map<String, Double>,
        callback: (ApiResult) -> Unit,
    ) {
        executor.execute {
            val endpointUrl = "${baseUrl.trimEnd('/')}/api/clinical/multi_agent_consensus"
            val payload = JSONObject().apply {
                put("patient_id", patientId)
                val vitalsObj = JSONObject()
                vitals.forEach { (k, v) -> vitalsObj.put(k, v) }
                put("vitals", vitalsObj)
            }
            val result = executePostJson(endpointUrl, payload.toString())
            callback(result)
        }
    }

    fun checkHealthAsync(callback: (Boolean, String) -> Unit) {
        executor.execute {
            val endpointUrl = "${baseUrl.trimEnd('/')}/api/status"
            try {
                val url = URL(endpointUrl)
                val conn = (url.openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"
                    connectTimeout = 8_000
                    readTimeout = 8_000
                    setRequestProperty("Accept", "application/json")
                }
                val code = conn.responseCode
                val body = if (code in 200..299) conn.inputStream.bufferedReader().use(BufferedReader::readText) else ""
                conn.disconnect()
                callback(code in 200..299, body)
            } catch (e: Exception) {
                callback(false, e.message ?: "Conexão recusada")
            }
        }
    }

    private fun enqueueOutbox(request: WearableIngestRequest) {
        synchronized(outboxLock) {
            if (outboxQueue.size < MAX_OUTBOX_SIZE) {
                outboxQueue.offer(request)
                persistOutboxLocked()
                Log.w(TAG, "Falha de rede. Pacote enfileirado no Outbox. Total pendente: ${outboxQueue.size}")
            }
        }
    }

    private fun flushOutboxAsync() {
        if (!isFlushing.compareAndSet(false, true)) return
        executor.execute {
            try {
                Log.i(TAG, "Iniciando esvaziamento do Outbox (${outboxQueue.size} pacotes)...")
                while (outboxQueue.isNotEmpty()) {
                    val req = outboxQueue.peek() ?: break
                    val res = ingestRealtimeSync(req)
                    if (res.ok) {
                        synchronized(outboxLock) {
                            outboxQueue.poll()
                            persistOutboxLocked()
                        }
                    } else {
                        Log.w(TAG, "Pausa no flush do Outbox: servidor respondeu com código ${res.httpCode}")
                        break
                    }
                }
            } finally {
                isFlushing.set(false)
            }
        }
    }

    /** Deve ser chamado apenas dentro de um bloco `synchronized(outboxLock)`. */
    private fun persistOutboxLocked() {
        try {
            val arr = JSONArray()
            outboxQueue.forEach { arr.put(it.toJsonObject()) }
            outboxFile.writeText(arr.toString())
        } catch (e: Exception) {
            Log.e(TAG, "Falha ao persistir Outbox em disco: ${e.message}")
        }
    }

    private fun loadPersistedOutbox() {
        try {
            if (!outboxFile.exists()) return
            val text = outboxFile.readText()
            if (text.isBlank()) return
            val arr = JSONArray(text)
            for (i in 0 until arr.length()) {
                outboxQueue.offer(WearableIngestRequest.fromJsonObject(arr.getJSONObject(i)))
            }
            if (outboxQueue.isNotEmpty()) {
                Log.i(TAG, "Outbox restaurado do disco: ${outboxQueue.size} pacotes pendentes.")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Falha ao restaurar Outbox do disco (arquivo será descartado): ${e.message}")
            outboxFile.delete()
        }
    }

    private fun executePostJson(endpointUrl: String, jsonString: String): ApiResult {
        var conn: HttpURLConnection? = null
        return try {
            val url = URL(endpointUrl)
            conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 15_000
                readTimeout = 20_000
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                if (apiKey.isNotBlank()) {
                    setRequestProperty("X-API-Key", apiKey)
                }
                setRequestProperty("Accept", "application/json")
                setRequestProperty("User-Agent", "HealthTech-Companion-VE30/3.1.0 (Android)")
            }

            OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(jsonString) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val body = stream?.bufferedReader()?.use(BufferedReader::readText).orEmpty()

            var parsedResponse: AiInferenceResponse? = null
            if (code in 200..299 && body.isNotBlank()) {
                parsedResponse = parseAiResponse(code, body)
            }

            ApiResult(httpCode = code, body = body, ok = code in 200..299, parsedAiResponse = parsedResponse)
        } catch (e: Exception) {
            Log.e(TAG, "Erro na requisição para $endpointUrl: ${e.message}")
            ApiResult(httpCode = 0, body = e.message ?: "Erro de conexão de rede", ok = false)
        } finally {
            conn?.disconnect()
        }
    }

    private fun parseAiResponse(httpCode: Int, body: String): AiInferenceResponse {
        return try {
            val json = JSONObject(body)
            val phantomMap = mutableMapOf<String, PhantomStateEstimate>()
            if (json.has("phantom_data")) {
                val phantomObj = json.optJSONObject("phantom_data")
                phantomObj?.keys()?.forEach { k ->
                    val v = phantomObj.optJSONObject(k)
                    if (v != null) {
                        phantomMap[k] = PhantomStateEstimate(
                            estimate = v.optDouble("estimate", 0.0),
                            ci_lower = v.optDouble("ci_lower", 0.0),
                            ci_upper = v.optDouble("ci_upper", 0.0),
                            is_reliable = v.optBoolean("is_reliable", true)
                        )
                    }
                }
            }

            AiInferenceResponse(
                status = json.optString("status", "success"),
                patient_id = json.optString("patient_id", null),
                device_id = json.optString("device_id", null),
                phantom_data = if (phantomMap.isNotEmpty()) phantomMap else null,
                anomaly_detection = null,
                diagnostic_hypotheses = null,
                multi_agent_consensus = null,
                clinical_alerts = null,
                detail = json.optString("detail", null),
                http_code = httpCode,
                ok = httpCode in 200..299
            )
        } catch (e: Exception) {
            AiInferenceResponse(
                status = "parse_fallback",
                patient_id = null,
                device_id = null,
                phantom_data = null,
                anomaly_detection = null,
                diagnostic_hypotheses = null,
                multi_agent_consensus = null,
                clinical_alerts = null,
                detail = body,
                http_code = httpCode,
                ok = httpCode in 200..299
            )
        }
    }

    companion object {
        private const val TAG = "HealthtechApiClient"
        private const val OUTBOX_FILE_NAME = "ve30_outbox_queue.json"
        private const val MAX_OUTBOX_SIZE = 500
    }
}
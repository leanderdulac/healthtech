package com.healthtech.companion.net

import com.healthtech.companion.net.dto.WearableIngestRequest
import com.healthtech.companion.net.outbox.OutboxFlusher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Exemplos de uso (copie para ViewModel / UseCase).
 * Não é Activity — só referência de integração.
 */
object UsageExample {

    fun wireFromBuildConfig(
        baseUrl: String,
        ingestApiKey: String,
        patientId: String,
        debug: Boolean,
        scope: CoroutineScope,
    ) {
        val repo = HealthtechRepository.create(
            baseUrl = baseUrl,
            apiKey = ingestApiKey,
            enableHttpLogging = debug,
        )
        val outbox = OutboxFlusher(repo)

        // 1) Smoke na abertura do app
        scope.launch(Dispatchers.IO) {
            when (val h = repo.health()) {
                is ApiResult.Success -> { /* UI: online */ }
                is ApiResult.Failure -> { /* UI: offline / API down */ }
            }
        }

        // 2) HR vindo do SDK (debounce no collector BLE)
        fun onHeartFromSdk(bpm: Double, mac: String) {
            val req = WearableIngestRequest(
                patientId = patientId,
                deviceId = if (mac.startsWith("HBAND-")) mac else "HBAND-$mac",
                heartRate = bpm,
                filterType = "BMO",
                ingestSource = "ble_hband",
            )
            // Preferir outbox: sobrevive a perda de rede
            outbox.enqueue(req)
            scope.launch(Dispatchers.IO) {
                outbox.flush(preferBatch = false)
            }
        }

        // 3) Flush periódico (WorkManager a cada 15 min)
        scope.launch(Dispatchers.IO) {
            outbox.flush(preferBatch = true)
        }

        // 4) Tela “última no servidor”
        scope.launch(Dispatchers.IO) {
            when (val latest = repo.latest(patientId)) {
                is ApiResult.Success -> { /* bind UI */ }
                is ApiResult.Failure -> {
                    if (latest.isUnauthorized) { /* reconfigurar key */ }
                }
            }
        }

        // silencia unused warning no esboço
        @Suppress("UNUSED_VARIABLE")
        val unused = ::onHeartFromSdk
    }
}

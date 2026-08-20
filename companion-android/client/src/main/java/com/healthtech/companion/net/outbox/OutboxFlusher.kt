package com.healthtech.companion.net.outbox

import com.healthtech.companion.net.ApiResult
import com.healthtech.companion.net.HealthtechRepository
import com.healthtech.companion.net.dto.WearableIngestRequest

/**
 * Flush da outbox em memória (protótipo).
 * No app real: Room DAO + WorkManager chamando [flush].
 *
 * Estratégia:
 * - 1 item  → POST /ingest
 * - N items → POST /batch-ingest (chunks ≤ 200), mesmo patient_id
 */
class OutboxFlusher(
    private val repository: HealthtechRepository,
    private val store: MutableList<OutboxItem> = mutableListOf(),
) {
    fun enqueue(request: WearableIngestRequest): OutboxItem {
        val item = OutboxItem(payload = request)
        store += item
        return item
    }

    fun pending(): List<OutboxItem> =
        store.filter {
            it.status == OutboxStatus.PENDING &&
                it.nextAttemptAtMs <= System.currentTimeMillis()
        }

    fun all(): List<OutboxItem> = store.toList()

    /**
     * Processa pendentes. Retorna resumo para log/UI.
     */
    suspend fun flush(preferBatch: Boolean = true): FlushSummary {
        val due = pending()
        if (due.isEmpty()) return FlushSummary()

        var sent = 0
        var dead = 0
        var failed = 0
        var auth = 0

        if (!preferBatch || due.size == 1) {
            for (item in due) {
                when (flushOne(item)) {
                    is FlushItemResult.Sent -> sent++
                    is FlushItemResult.Dead -> dead++
                    is FlushItemResult.Auth -> auth++
                    is FlushItemResult.Retry -> failed++
                }
            }
        } else {
            // Agrupa por patient_id
            due.groupBy { it.payload.patientId }.forEach { (patientId, items) ->
                items.chunked(OutboxPolicy.MAX_BATCH).forEach { chunk ->
                    when (flushBatch(patientId, chunk)) {
                        is FlushItemResult.Sent -> sent += chunk.size
                        is FlushItemResult.Dead -> dead += chunk.size
                        is FlushItemResult.Auth -> auth += chunk.size
                        is FlushItemResult.Retry -> failed += chunk.size
                    }
                }
            }
        }

        return FlushSummary(sent = sent, dead = dead, failed = failed, authFailures = auth)
    }

    private suspend fun flushOne(item: OutboxItem): FlushItemResult {
        markSending(item)
        return when (val result = repository.ingest(item.payload)) {
            is ApiResult.Success -> {
                markSent(item)
                FlushItemResult.Sent
            }
            is ApiResult.Failure -> handleFailure(item, result.httpCode, result.message)
        }
    }

    private suspend fun flushBatch(
        patientId: String,
        items: List<OutboxItem>,
    ): FlushItemResult {
        items.forEach { markSending(it) }
        return when (
            val result = repository.batchIngest(
                patientId,
                items.map { it.payload },
            )
        ) {
            is ApiResult.Success -> {
                items.forEach { markSent(it) }
                FlushItemResult.Sent
            }
            is ApiResult.Failure -> {
                // Em 422 do batch, marca todos dead; em 5xx requeue individual
                items.forEach { handleFailure(it, result.httpCode, result.message) }
                handleFailure(items.first(), result.httpCode, result.message)
            }
        }
    }

    private fun handleFailure(
        item: OutboxItem,
        httpCode: Int,
        message: String,
    ): FlushItemResult {
        return when {
            OutboxPolicy.isAuthFailure(httpCode) -> {
                update(item) {
                    copy(
                        status = OutboxStatus.PENDING,
                        lastHttpCode = httpCode,
                        lastError = message,
                        attempts = attempts + 1,
                        nextAttemptAtMs = Long.MAX_VALUE / 4, // pausa até reconfigurar key
                    )
                }
                FlushItemResult.Auth
            }
            OutboxPolicy.isDeadLetter(httpCode) -> {
                update(item) {
                    copy(
                        status = OutboxStatus.DEAD,
                        lastHttpCode = httpCode,
                        lastError = message,
                        attempts = attempts + 1,
                    )
                }
                FlushItemResult.Dead
            }
            OutboxPolicy.shouldRetry(httpCode) -> {
                val nextAttempts = item.attempts + 1
                if (nextAttempts >= OutboxPolicy.MAX_ATTEMPTS) {
                    update(item) {
                        copy(
                            status = OutboxStatus.DEAD,
                            lastHttpCode = httpCode,
                            lastError = "max attempts: $message",
                            attempts = nextAttempts,
                        )
                    }
                    FlushItemResult.Dead
                } else {
                    update(item) {
                        copy(
                            status = OutboxStatus.PENDING,
                            lastHttpCode = httpCode,
                            lastError = message,
                            attempts = nextAttempts,
                            nextAttemptAtMs = System.currentTimeMillis() +
                                OutboxPolicy.nextBackoffMs(nextAttempts),
                        )
                    }
                    FlushItemResult.Retry
                }
            }
            else -> {
                update(item) {
                    copy(
                        status = OutboxStatus.DEAD,
                        lastHttpCode = httpCode,
                        lastError = message,
                        attempts = attempts + 1,
                    )
                }
                FlushItemResult.Dead
            }
        }
    }

    private fun markSending(item: OutboxItem) {
        update(item) { copy(status = OutboxStatus.SENDING) }
    }

    private fun markSent(item: OutboxItem) {
        update(item) {
            copy(status = OutboxStatus.SENT, lastError = null, lastHttpCode = 200)
        }
    }

    private fun update(item: OutboxItem, transform: OutboxItem.() -> OutboxItem) {
        val idx = store.indexOfFirst { it.id == item.id }
        if (idx >= 0) store[idx] = store[idx].transform()
    }

    data class FlushSummary(
        val sent: Int = 0,
        val dead: Int = 0,
        val failed: Int = 0,
        val authFailures: Int = 0,
    )

    private sealed class FlushItemResult {
        data object Sent : FlushItemResult()
        data object Dead : FlushItemResult()
        data object Retry : FlushItemResult()
        data object Auth : FlushItemResult()
    }
}

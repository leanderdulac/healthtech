package com.healthtech.companion.net.outbox

import com.healthtech.companion.net.dto.WearableIngestRequest
import java.util.UUID

enum class OutboxStatus {
    PENDING,
    SENDING,
    SENT,
    DEAD,
}

/**
 * Item da fila offline. Persista com Room no app real.
 */
data class OutboxItem(
    val id: String = UUID.randomUUID().toString(),
    val payload: WearableIngestRequest,
    val status: OutboxStatus = OutboxStatus.PENDING,
    val createdAtMs: Long = System.currentTimeMillis(),
    val nextAttemptAtMs: Long = System.currentTimeMillis(),
    val attempts: Int = 0,
    val lastError: String? = null,
    val lastHttpCode: Int? = null,
)

/**
 * Decisão de retry a partir do HTTP code (espelha ARCHITECTURE_ONEPAGER).
 */
object OutboxPolicy {
    const val MAX_ATTEMPTS = 12
    const val MAX_BATCH = 200
    const val BASE_BACKOFF_MS = 2_000L
    const val MAX_BACKOFF_MS = 300_000L // 5 min

    fun shouldRetry(httpCode: Int): Boolean =
        httpCode == 0 || httpCode == 408 || httpCode == 429 || httpCode in 500..599

    fun isDeadLetter(httpCode: Int): Boolean =
        httpCode == 422

    fun isAuthFailure(httpCode: Int): Boolean =
        httpCode == 401 || httpCode == 403

    fun nextBackoffMs(attempts: Int): Long {
        val exp = (BASE_BACKOFF_MS * (1L shl attempts.coerceAtMost(8)))
        val jitter = (0..500).random().toLong()
        return (exp + jitter).coerceAtMost(MAX_BACKOFF_MS)
    }
}

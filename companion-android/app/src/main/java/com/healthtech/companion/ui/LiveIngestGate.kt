package com.healthtech.companion.ui

/**
 * Junta FC, SpO2, pressão e temperatura da mesma sessão e segura o envio
 * por alguns segundos sem descartar a amostra mais nova.
 */
class LiveIngestGate(
    private val minIntervalMs: Long = 3_000L,
) {
    data class Snapshot(
        val generation: Int,
        val bpm: Int,
        val deviceId: String,
        val source: String,
        val spo2: Int? = null,
        val bpSys: Int? = null,
        val bpDia: Int? = null,
        val tempC: Double? = null,
    )

    private var lastSentAt = 0L
    private var pending = false
    private var latest: Snapshot? = null

    fun offer(snapshot: Snapshot, nowMs: Long): Snapshot? {
        latest = snapshot
        if (lastSentAt != 0L && nowMs - lastSentAt < minIntervalMs) {
            pending = true
            return null
        }
        pending = false
        lastSentAt = nowMs
        return snapshot
    }

    fun pollDue(nowMs: Long): Snapshot? {
        val snap = latest ?: return null
        if (!pending || nowMs - lastSentAt < minIntervalMs) return null
        pending = false
        lastSentAt = nowMs
        return snap
    }

    fun millisUntilDue(nowMs: Long): Long {
        if (!pending) return 0L
        return (minIntervalMs - (nowMs - lastSentAt)).coerceAtLeast(0L)
    }

    fun clear() {
        latest = null
        pending = false
        lastSentAt = 0L
    }
}

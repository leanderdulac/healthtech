package com.healthtech.companion.ble

/**
 * A pulseira HBand mede FC e SpO2 em série. O SDK recusa as duas ao mesmo tempo.
 *
 * Depois de uma FC normal, espera [settleMs] para alguns batimentos saírem,
 * para o sensor cardíaco, mede um SpO2 e só então volta à FC.
 * A próxima troca espera [intervalMs] desde o fim da medição anterior.
 */
class Spo2Cycle(
    private val settleMs: Long = 12_000L,
    private val intervalMs: Long = 60_000L,
) {
    var armed: Boolean = false
        private set

    var measuring: Boolean = false
        private set

    private var lastFinishedAtMs: Long = 0L

    /** Atraso até parar a FC. Null enquanto a troca não deve ser marcada. */
    fun onNormalHeart(nowMs: Long): Long? {
        if (measuring || armed) return null
        if (lastFinishedAtMs != 0L && nowMs - lastFinishedAtMs < intervalMs) return null
        armed = true
        return settleMs
    }

    fun beginMeasurement(): Boolean {
        if (measuring) return false
        armed = false
        measuring = true
        return true
    }

    fun finish(nowMs: Long) {
        measuring = false
        armed = false
        lastFinishedAtMs = nowMs
    }

    fun cancel() {
        measuring = false
        armed = false
    }
}

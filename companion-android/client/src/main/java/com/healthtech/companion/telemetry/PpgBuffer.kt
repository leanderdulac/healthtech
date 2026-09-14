package com.healthtech.companion.telemetry

import java.util.ArrayDeque

/**
 * Buffer PPG ordenado com capacidade (janela deslizante).
 *
 * O agregador VE30 antigo usava `ConcurrentHashMap.newKeySet<Double>()`,
 * o que descartava amostras repetidas e embaralhava a ordem — inútil para BMO.
 */
class PpgBuffer(val capacity: Int = DEFAULT_CAPACITY) {
    private val samples = ArrayDeque<Double>(capacity)

    init {
        require(capacity > 0) { "capacity deve ser > 0" }
    }

    @Synchronized
    fun append(sample: Double) {
        if (!sample.isFinite()) return
        while (samples.size >= capacity) {
            samples.removeFirst()
        }
        samples.addLast(sample)
    }

    /** Remove e devolve as amostras na ordem de chegada. */
    @Synchronized
    fun drain(): List<Double> {
        if (samples.isEmpty()) return emptyList()
        val out = ArrayList<Double>(samples.size)
        while (samples.isNotEmpty()) {
            out.add(samples.removeFirst())
        }
        return out
    }

    @Synchronized
    fun snapshot(): List<Double> = samples.toList()

    @Synchronized
    fun size(): Int = samples.size

    @Synchronized
    fun clear() {
        samples.clear()
    }

    companion object {
        const val DEFAULT_CAPACITY = 64
    }
}

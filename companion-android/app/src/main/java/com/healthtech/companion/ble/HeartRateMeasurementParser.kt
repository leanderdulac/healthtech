package com.healthtech.companion.ble

/**
 * Parser da característica Heart Rate Measurement (UUID 0x2A37, Bluetooth SIG).
 *
 * Flags (byte 0):
 *  bit0 = 0 → HR UINT8; 1 → HR UINT16 LE
 *  bit1-2 = sensor contact
 *  bit3 = energy expended presente
 *  bit4 = RR intervals presentes
 *
 * Bug clássico: tratar o byte de flags como BPM, ou ler 1 byte quando o device
 * envia UINT16 — gera valores "quase certos" mas errados.
 */
object HeartRateMeasurementParser {

    fun parseBpm(value: ByteArray?): Int? {
        if (value == null || value.isEmpty()) return null
        val flags = value[0].toInt() and 0xFF
        val hr16 = flags and 0x01 != 0
        val bpm = if (hr16) {
            if (value.size < 3) return null
            (value[1].toInt() and 0xFF) or ((value[2].toInt() and 0xFF) shl 8)
        } else {
            if (value.size < 2) return null
            value[1].toInt() and 0xFF
        }
        return bpm.takeIf { it in 20..250 }
    }
}

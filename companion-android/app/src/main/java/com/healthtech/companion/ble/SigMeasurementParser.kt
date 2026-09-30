package com.healthtech.companion.ble

import kotlin.math.pow

/**
 * Medidas dos perfis Bluetooth SIG usados por smartwatches genéricos.
 * Sem dependência de Android, para o teste unitário rodar na JVM.
 */
object SigMeasurementParser {

    fun heartRateBpm(value: ByteArray?): Int? = HeartRateMeasurementParser.parseBpm(value)

    /** PLX spot-check (0x2A5E) ou continuous (0x2A5F): flags + SpO2 SFLOAT. */
    fun pulseOximeterPercent(value: ByteArray?): Int? {
        if (value == null || value.size < 3) return null
        val spo2 = sfloat(u16(value, 1)) ?: return null
        return spo2.toInt().takeIf { it in 50..100 }
    }

    /**
     * Blood Pressure Measurement (0x2A35).
     * Bit 0 das flags: 0 = mmHg, 1 = kPa.
     */
    fun bloodPressureMmhg(value: ByteArray?): Pair<Int, Int>? {
        if (value == null || value.size < 7) return null
        val flags = value[0].toInt() and 0xFF
        val inKpa = flags and 0x01 != 0
        val systolic = sfloat(u16(value, 1)) ?: return null
        val diastolic = sfloat(u16(value, 3)) ?: return null
        val sys = if (inKpa) systolic * KPA_TO_MMHG else systolic
        val dia = if (inKpa) diastolic * KPA_TO_MMHG else diastolic
        val sysI = sys.toInt()
        val diaI = dia.toInt()
        if (sysI !in 50..300 || diaI !in 30..200 || diaI >= sysI) return null
        return sysI to diaI
    }

    /** Temperature Measurement (0x2A1C). Bit 0 das flags: 0 = °C, 1 = °F. */
    fun temperatureCelsius(value: ByteArray?): Double? {
        if (value == null || value.size < 5) return null
        val flags = value[0].toInt() and 0xFF
        val raw = float32(value, 1) ?: return null
        val celsius = if (flags and 0x01 != 0) (raw - 32.0) * 5.0 / 9.0 else raw
        return celsius.takeIf { it in 30.0..45.0 }
    }

    fun sfloat(raw: Int): Double? {
        var mantissa = raw and 0x0FFF
        if (mantissa >= 0x0800) mantissa -= 0x1000
        if (mantissa == 0x07FF || mantissa == -2048) return null
        var exponent = (raw shr 12) and 0x0F
        if (exponent >= 0x08) exponent -= 0x10
        return mantissa * 10.0.pow(exponent)
    }

    fun float32(value: ByteArray, offset: Int): Double? {
        if (value.size < offset + 4) return null
        var mantissa = (value[offset].toInt() and 0xFF) or
            ((value[offset + 1].toInt() and 0xFF) shl 8) or
            ((value[offset + 2].toInt() and 0xFF) shl 16)
        if (mantissa and 0x800000 != 0) mantissa -= 0x1000000
        if (mantissa == 0x7FFFFF || mantissa == -0x800000) return null
        var exponent = value[offset + 3].toInt()
        if (exponent >= 128) exponent -= 256
        return mantissa * 10.0.pow(exponent)
    }

    private fun u16(value: ByteArray, offset: Int): Int =
        (value[offset].toInt() and 0xFF) or ((value[offset + 1].toInt() and 0xFF) shl 8)

    private const val KPA_TO_MMHG = 7.5006168
}

fun prefersVeepooProtocol(name: String?): Boolean {
    val n = (name ?: "").lowercase()
    return n.contains("hband") || n.contains("veepoo") || n.contains("ve30")
}

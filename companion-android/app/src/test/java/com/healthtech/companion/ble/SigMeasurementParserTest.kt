package com.healthtech.companion.ble

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SigMeasurementParserTest {

    @Test
    fun heartRateUint8() {
        assertEquals(72, SigMeasurementParser.heartRateBpm(byteArrayOf(0x00, 72)))
    }

    @Test
    fun heartRateUint16() {
        assertEquals(180, SigMeasurementParser.heartRateBpm(byteArrayOf(0x01, 0xB4.toByte(), 0x00)))
    }

    @Test
    fun heartRateRejectsWristOff() {
        assertNull(SigMeasurementParser.heartRateBpm(byteArrayOf(0x02, 72)))
        assertEquals(72, SigMeasurementParser.heartRateBpm(byteArrayOf(0x06, 72)))
    }

    @Test
    fun spo2FromSfloat() {
        assertEquals(98, SigMeasurementParser.pulseOximeterPercent(byteArrayOf(0x00, 0x62, 0x00)))
    }

    @Test
    fun bloodPressureKpaConvertsToMmhg() {
        val raw = byteArrayOf(
            0x01,
            0xA0.toByte(), 0xF0.toByte(),
            0x2B, 0xE4.toByte(),
            0xA0.toByte(), 0xF0.toByte(),
        )
        val bp = SigMeasurementParser.bloodPressureMmhg(raw)
        assertEquals(120, bp?.first)
        assertEquals(80, bp?.second)
    }

    @Test
    fun temperatureCelsius() {
        val raw = byteArrayOf(0x00, 0x6D, 0x01, 0x00, 0xFF.toByte())
        val temp = SigMeasurementParser.temperatureCelsius(raw)
        assertEquals(36.5, temp!!, 0.05)
    }

    @Test
    fun rejectsEmpty() {
        assertNull(SigMeasurementParser.heartRateBpm(byteArrayOf()))
        assertNull(SigMeasurementParser.pulseOximeterPercent(null))
    }

    @Test
    fun veepooNameDoesNotStealGenericWatch() {
        assertEquals(true, prefersVeepooProtocol("HBand 8"))
        assertEquals(true, prefersVeepooProtocol("VE30"))
        assertEquals(false, prefersVeepooProtocol("Polar H10"))
        assertEquals(false, prefersVeepooProtocol("Galaxy Watch"))
    }
}

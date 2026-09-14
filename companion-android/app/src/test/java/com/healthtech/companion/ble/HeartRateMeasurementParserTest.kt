package com.healthtech.companion.ble

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HeartRateMeasurementParserTest {

    @Test
    fun uint8HrIsNotTheFlagsByte() {
        assertEquals(78, HeartRateMeasurementParser.parseBpm(byteArrayOf(0x00, 78)))
        assertNull(HeartRateMeasurementParser.parseBpm(byteArrayOf(0x00)))
    }

    @Test
    fun uint16LittleEndian() {
        assertEquals(100, HeartRateMeasurementParser.parseBpm(byteArrayOf(0x01, 100, 0)))
        assertNull(HeartRateMeasurementParser.parseBpm(byteArrayOf(0x01, 0x2C, 0x01)))
    }

    @Test
    fun rejectsOutOfRange() {
        assertNull(HeartRateMeasurementParser.parseBpm(byteArrayOf(0x00, 5)))
        assertNull(HeartRateMeasurementParser.parseBpm(byteArrayOf(0x00.toByte(), 251.toByte())))
    }
}

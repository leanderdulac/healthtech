package com.healthtech.companion.ble

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Spo2CycleTest {

    @Test
    fun waitsForHeartSamplesThenMeasuresOnce() {
        val cycle = Spo2Cycle(settleMs = 12_000L, intervalMs = 60_000L)
        assertEquals(12_000L, cycle.onNormalHeart(nowMs = 1_000L))
        assertTrue(cycle.armed)
        assertNull(cycle.onNormalHeart(nowMs = 2_000L))

        assertTrue(cycle.beginMeasurement())
        assertTrue(cycle.measuring)
        assertFalse(cycle.armed)
        cycle.finish(nowMs = 20_000L)

        assertNull(cycle.onNormalHeart(nowMs = 50_000L))
        assertEquals(12_000L, cycle.onNormalHeart(nowMs = 80_000L))
    }

    @Test
    fun cancelLetsTheNextHeartRearm() {
        val cycle = Spo2Cycle(settleMs = 12_000L, intervalMs = 60_000L)
        assertEquals(12_000L, cycle.onNormalHeart(nowMs = 0L))
        cycle.cancel()
        assertFalse(cycle.armed)
        assertEquals(12_000L, cycle.onNormalHeart(nowMs = 1_000L))
    }
}

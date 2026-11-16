package com.healthtech.companion.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LiveIngestGateTest {

    @Test
    fun keepsTheNewestSampleWhenThrottled() {
        val gate = LiveIngestGate(minIntervalMs = 3_000L)
        val first = sample(bpm = 70, spo2 = null)
        assertEquals(first, gate.offer(first, nowMs = 10_000L))

        val newer = sample(bpm = 70, spo2 = 98)
        assertNull(gate.offer(newer, nowMs = 11_000L))
        assertNull(gate.pollDue(nowMs = 12_000L))
        assertEquals(newer, gate.pollDue(nowMs = 13_000L))
    }

    @Test
    fun clearDropsPendingSampleFromThePreviousWatch() {
        val gate = LiveIngestGate(minIntervalMs = 3_000L)
        gate.offer(sample(bpm = 80, spo2 = 97), nowMs = 1_000L)
        gate.offer(sample(bpm = 81, spo2 = 96), nowMs = 1_500L)
        gate.clear()
        assertNull(gate.pollDue(nowMs = 9_000L))
        val fresh = sample(bpm = 60, spo2 = null)
        assertEquals(fresh, gate.offer(fresh, nowMs = 2_000L))
    }

    private fun sample(bpm: Int, spo2: Int?) = LiveIngestGate.Snapshot(
        generation = 1,
        bpm = bpm,
        deviceId = "WATCH-1",
        source = "ble_standard",
        spo2 = spo2,
    )
}

package com.healthtech.companion.telemetry

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PpgBufferTest {

    @Test
    fun `keeps insertion order and drains`() {
        val buf = PpgBuffer(capacity = 8)
        buf.append(1.0)
        buf.append(1.0) // set-based buffer would have dropped the duplicate
        buf.append(2.0)
        assertEquals(listOf(1.0, 1.0, 2.0), buf.snapshot())
        assertEquals(listOf(1.0, 1.0, 2.0), buf.drain())
        assertTrue(buf.snapshot().isEmpty())
    }

    @Test
    fun `drops oldest when over capacity`() {
        val buf = PpgBuffer(capacity = 3)
        buf.append(10.0)
        buf.append(20.0)
        buf.append(30.0)
        buf.append(40.0)
        assertEquals(listOf(20.0, 30.0, 40.0), buf.drain())
    }

    @Test
    fun `ignores non-finite samples`() {
        val buf = PpgBuffer(capacity = 4)
        buf.append(Double.NaN)
        buf.append(Double.POSITIVE_INFINITY)
        buf.append(42.0)
        assertEquals(listOf(42.0), buf.drain())
    }
}

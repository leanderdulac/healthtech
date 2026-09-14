package com.healthtech.companion.telemetry

import org.junit.Assert.assertEquals
import org.junit.Test

class DeviceIdsTest {

    @Test
    fun `prefixes bare MAC with HBAND`() {
        assertEquals("HBAND-AA:BB:CC:DD:EE:FF", DeviceIds.fromMac("AA:BB:CC:DD:EE:FF"))
    }

    @Test
    fun `keeps existing HBAND and GATT prefixes`() {
        assertEquals("HBAND-AA:BB:CC:DD:EE:FF", DeviceIds.fromMac("HBAND-AA:BB:CC:DD:EE:FF"))
        assertEquals("GATT-AA:BB:CC:DD:EE:FF", DeviceIds.fromMac("GATT-AA:BB:CC:DD:EE:FF"))
    }

    @Test
    fun `rewrites legacy VE30 prefix to HBAND contract`() {
        assertEquals("HBAND-E4:65:08:AA:BB:CC", DeviceIds.fromMac("VE30-E4:65:08:AA:BB:CC"))
    }

    @Test
    fun `blank mac becomes UNKNOWN`() {
        assertEquals(DeviceIds.UNKNOWN, DeviceIds.fromMac(null))
        assertEquals(DeviceIds.UNKNOWN, DeviceIds.fromMac("  "))
    }
}

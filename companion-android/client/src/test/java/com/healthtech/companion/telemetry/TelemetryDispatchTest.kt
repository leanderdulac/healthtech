package com.healthtech.companion.telemetry

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TelemetryDispatchTest {

    @Test
    fun `does not dispatch without a real heart rate`() {
        assertNull(
            TelemetryDispatch.buildRealtime(
                patientId = "PAT-HBAND-001",
                deviceId = "HBAND-AA:BB:CC:DD:EE:FF",
                heartRate = null,
                spo2 = 98.0,
            ),
        )
        assertNull(
            TelemetryDispatch.buildRealtime(
                patientId = "PAT-HBAND-001",
                deviceId = "HBAND-AA:BB:CC:DD:EE:FF",
                heartRate = 0.0,
            ),
        )
        assertNull(
            TelemetryDispatch.buildRealtime(
                patientId = "PAT-HBAND-001",
                deviceId = "HBAND-AA:BB:CC:DD:EE:FF",
                heartRate = 12.0,
            ),
        )
        // 72 era o default fabricado do agregador antigo; só é válido se veio de leitura real.
        val realSeventyTwo = TelemetryDispatch.buildRealtime(
            patientId = "PAT-HBAND-001",
            deviceId = "HBAND-AA:BB:CC:DD:EE:FF",
            heartRate = 72.0,
        )
        requireNotNull(realSeventyTwo)
        assertEquals(72.0, realSeventyTwo.heartRate, 0.0)
        assertNull(realSeventyTwo.spo2)
    }

    @Test
    fun `does not invent spo2 temp or hrv when absent`() {
        val req = TelemetryDispatch.buildRealtime(
            patientId = "PAT-HBAND-001",
            deviceId = "HBAND-AA:BB:CC:DD:EE:FF",
            heartRate = 78.0,
        )
        requireNotNull(req)
        assertEquals(78.0, req.heartRate, 0.0)
        assertNull(req.spo2)
        assertNull(req.skinTemp)
        assertNull(req.hrvRmssd)
        assertNull(req.bloodPressureSys)
        assertNull(req.ppgSignal)
        assertEquals("ble_hband", req.ingestSource)
    }

    @Test
    fun `includes only in-range optional vitals`() {
        val req = TelemetryDispatch.buildRealtime(
            patientId = "PAT-HBAND-001",
            deviceId = "HBAND-AA:BB:CC:DD:EE:FF",
            heartRate = 81.0,
            spo2 = 97.0,
            skinTemp = 33.4,
            bloodPressureSys = 122.0,
            bloodPressureDia = 81.0,
            hrvRmssd = 44.0,
            ppgSignal = listOf(500.0, 520.0),
        )
        requireNotNull(req)
        assertEquals(97.0, req.spo2)
        assertEquals(33.4, req.skinTemp)
        assertEquals(122.0, req.bloodPressureSys)
        assertEquals(81.0, req.bloodPressureDia)
        assertEquals(44.0, req.hrvRmssd)
        assertEquals(listOf(500.0, 520.0), req.ppgSignal)
    }

    @Test
    fun `drops out-of-range optional vitals and incomplete BP`() {
        val req = TelemetryDispatch.buildRealtime(
            patientId = "PAT-HBAND-001",
            deviceId = "HBAND-AA:BB:CC:DD:EE:FF",
            heartRate = 80.0,
            spo2 = 120.0,
            skinTemp = 10.0,
            bloodPressureSys = 122.0,
            bloodPressureDia = null,
            hrvRmssd = 900.0,
        )
        requireNotNull(req)
        assertNull(req.spo2)
        assertNull(req.skinTemp)
        assertNull(req.bloodPressureSys)
        assertNull(req.bloodPressureDia)
        assertNull(req.hrvRmssd)
    }

    @Test
    fun `origin sample without HR is skipped`() {
        assertNull(
            TelemetryDispatch.fromOriginSample(
                OriginVitalSample(spo2 = 98.0, timestampIso = "2026-08-06T08:00:00Z"),
                patientId = "PAT-HBAND-001",
                deviceId = "HBAND-AA:BB:CC:DD:EE:FF",
            ),
        )
    }

    @Test
    fun `origin sample with HR maps without fabricated defaults`() {
        val req = TelemetryDispatch.fromOriginSample(
            OriginVitalSample(
                timestampIso = "2026-08-06T08:05:00Z",
                heartRate = 75.0,
                spo2 = 97.0,
            ),
            patientId = "PAT-HBAND-001",
            deviceId = "HBAND-AA:BB:CC:DD:EE:FF",
        )
        requireNotNull(req)
        assertEquals(75.0, req.heartRate, 0.0)
        assertEquals(97.0, req.spo2)
        assertNull(req.skinTemp)
        assertEquals("2026-08-06T08:05:00Z", req.timestamp)
    }

    @Test
    fun `origin batch drops samples without HR and keeps real ones`() {
        val samples = listOf(
            OriginVitalSample(heartRate = null, spo2 = 98.0),
            OriginVitalSample(heartRate = 74.0, spo2 = 97.0, timestampIso = "2026-08-06T08:00:00Z"),
            OriginVitalSample(heartRate = 5.0),
        )
        val readings = samples.mapNotNull {
            TelemetryDispatch.fromOriginSample(
                it,
                patientId = "PAT-HBAND-001",
                deviceId = "HBAND-AA:BB:CC:DD:EE:FF",
            )
        }
        assertEquals(1, readings.size)
        assertEquals(74.0, readings[0].heartRate, 0.0)
        assertEquals(97.0, readings[0].spo2)
        assertNull(readings[0].skinTemp)
    }
}

package com.healthtech.companion.net

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DtosTest {

    @Test
    fun `WearableIngestRequest round-trips through JSON with all fields populated`() {
        val original = WearableIngestRequest(
            patient_id = "PAT-VE30-001",
            device_id = "VE30-E4:65:08:AA:BB:CC",
            heart_rate = 76.0,
            spo2 = 98.5,
            skin_temp = 33.4,
            blood_pressure_sys = 122.0,
            blood_pressure_dia = 81.0,
            hrv_rmssd = 44.0,
            activity_level = 1.2,
            steps = 1250,
            calories = 58.4,
            wear_status = true,
            ppg_signal = listOf(500.0, 520.0, 560.0, 610.0),
            filter_type = "BMO",
            timestamp = "2026-08-19T21:40:00Z",
            device_info = WearableDeviceInfo(
                device_id = "VE30-E4:65:08:AA:BB:CC",
                vendor = "hband",
                model = "VE30",
                battery_level = 88.0,
                mac_address = "E4:65:08:AA:BB:CC",
            ),
        )

        val restored = WearableIngestRequest.fromJsonObject(original.toJsonObject())

        assertEquals(original.patient_id, restored.patient_id)
        assertEquals(original.device_id, restored.device_id)
        assertEquals(original.heart_rate, restored.heart_rate)
        assertEquals(original.spo2, restored.spo2)
        assertEquals(original.skin_temp, restored.skin_temp)
        assertEquals(original.blood_pressure_sys, restored.blood_pressure_sys)
        assertEquals(original.blood_pressure_dia, restored.blood_pressure_dia)
        assertEquals(original.hrv_rmssd, restored.hrv_rmssd)
        assertEquals(original.steps, restored.steps)
        assertEquals(original.wear_status, restored.wear_status)
        assertEquals(original.ppg_signal, restored.ppg_signal)
        assertEquals(original.timestamp, restored.timestamp)
        assertEquals(original.device_info?.mac_address, restored.device_info?.mac_address)
        assertEquals(original.device_info?.battery_level, restored.device_info?.battery_level)
    }

    @Test
    fun `WearableIngestRequest round-trips through JSON with optional fields absent`() {
        val original = WearableIngestRequest(
            patient_id = "PAT-VE30-001",
            device_id = "VE30-DEFAULT",
        )

        val restored = WearableIngestRequest.fromJsonObject(original.toJsonObject())

        assertEquals(original.patient_id, restored.patient_id)
        assertEquals(original.device_id, restored.device_id)
        assertNull(restored.heart_rate)
        assertNull(restored.blood_pressure_sys)
        assertNull(restored.ppg_signal)
        assertNull(restored.device_info)
        assertTrue(restored.wear_status)
    }

    @Test
    fun `Outbox persistence round-trips a JSON array of requests`() {
        val queue = listOf(
            WearableIngestRequest(patient_id = "PAT-1", device_id = "DEV-1", heart_rate = 70.0),
            WearableIngestRequest(patient_id = "PAT-1", device_id = "DEV-1", heart_rate = 71.0),
        )

        val arr = org.json.JSONArray()
        queue.forEach { arr.put(it.toJsonObject()) }
        val serialized = arr.toString()

        val reloaded = mutableListOf<WearableIngestRequest>()
        val parsedArr = org.json.JSONArray(serialized)
        for (i in 0 until parsedArr.length()) {
            reloaded.add(WearableIngestRequest.fromJsonObject(parsedArr.getJSONObject(i)))
        }

        assertEquals(2, reloaded.size)
        assertEquals(70.0, reloaded[0].heart_rate)
        assertEquals(71.0, reloaded[1].heart_rate)
    }

    @Test
    fun `WearableDeviceInfo round-trips through JSON`() {
        val original = WearableDeviceInfo(
            device_id = "VE30-DEVICE",
            vendor = "hband",
            model = "VE30",
            firmware_version = "1.2.3",
            mac_address = "AA:BB:CC:DD:EE:FF",
            battery_level = 42.0,
            origin_protocol_version = 3,
            watchday = 7,
        )

        val restored = WearableDeviceInfo.fromJsonObject(original.toJsonObject())

        assertEquals(original, restored)
    }

    @Test
    fun `ApiResult classifies HTTP status codes correctly`() {
        assertTrue(ApiResult(httpCode = 401, body = "", ok = false).isUnauthorized)
        assertTrue(ApiResult(httpCode = 403, body = "", ok = false).isUnauthorized)
        assertTrue(ApiResult(httpCode = 404, body = "", ok = false).isClientError)
        assertTrue(ApiResult(httpCode = 500, body = "", ok = false).isServerError)
        assertTrue(ApiResult(httpCode = 200, body = "", ok = true).ok)
    }

    @Test
    fun `toJsonObject omits null optional fields`() {
        val request = WearableIngestRequest(patient_id = "P", device_id = "D")
        val json: JSONObject = request.toJsonObject()

        assertTrue(!json.has("heart_rate"))
        assertTrue(!json.has("ppg_signal"))
        assertTrue(!json.has("device"))
    }
}

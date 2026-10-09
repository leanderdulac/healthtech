package com.healthtech.companion.net.outbox

import com.healthtech.companion.net.dto.WearableIngestRequest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class FileOutboxStoreTest {

    @Test
    fun pendingItemSurvivesANewStoreAndSentItemsDoNot() {
        val file = File.createTempFile("outbox", ".json")
        file.deleteOnExit()
        val store = FileOutboxStore(file)
        val pending = OutboxItem(
            payload = WearableIngestRequest(
                patientId = "PAT-HBAND-001",
                deviceId = "HBAND-AA",
                heartRate = 82.0,
                spo2 = 96.0,
                ingestSource = "ble_hband",
            ),
        )
        val sent = pending.copy(
            id = "sent-1",
            status = OutboxStatus.SENT,
            payload = pending.payload.copy(heartRate = 70.0),
        )
        val items = mutableListOf(pending, sent)
        store.save(items)

        val loaded = FileOutboxStore(file).load()
        assertEquals(1, loaded.size)
        assertEquals(pending.id, loaded[0].id)
        assertEquals(82.0, loaded[0].payload.heartRate, 0.0)
        assertEquals(96.0, loaded[0].payload.spo2!!, 0.0)
        assertEquals(OutboxStatus.PENDING, loaded[0].status)
        assertTrue(items.none { it.status == OutboxStatus.SENT })
    }

    @Test
    fun corruptFileLoadsAsAnEmptyQueue() {
        val file = File.createTempFile("outbox-bad", ".json")
        file.deleteOnExit()
        file.writeText("{")
        assertEquals(0, FileOutboxStore(file).load().size)
    }
}

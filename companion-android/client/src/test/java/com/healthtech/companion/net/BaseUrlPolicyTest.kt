package com.healthtech.companion.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BaseUrlPolicyTest {

    @Test
    fun httpsIsAlwaysAccepted() {
        assertEquals(
            "https://api.example.com",
            BaseUrlPolicy.normalize("https://api.example.com/", allowPrivateCleartext = false),
        )
    }

    @Test
    fun releaseRejectsCleartext() {
        assertRejected("http://10.0.2.2:8080", allowPrivateCleartext = false)
        assertRejected("http://192.168.0.10:8080", allowPrivateCleartext = false)
    }

    @Test
    fun debugAllowsOnlyLocalAndPrivateHttp() {
        assertEquals(
            "http://10.0.2.2:8080",
            BaseUrlPolicy.normalize("http://10.0.2.2:8080", allowPrivateCleartext = true),
        )
        assertEquals(
            "http://192.168.0.10:8080",
            BaseUrlPolicy.normalize("http://192.168.0.10:8080/", allowPrivateCleartext = true),
        )
        assertTrue(BaseUrlPolicy.isLocalOrPrivate("10.1.2.3"))
        assertTrue(BaseUrlPolicy.isLocalOrPrivate("172.16.5.1"))
        assertFalse(BaseUrlPolicy.isLocalOrPrivate("8.8.8.8"))
        assertFalse(BaseUrlPolicy.isLocalOrPrivate("172.32.0.1"))
        assertRejected("http://api.example.com", allowPrivateCleartext = true)
        assertRejected("http://8.8.8.8", allowPrivateCleartext = true)
    }

    @Test
    fun rejectsCredentialsInTheUrl() {
        assertRejected("https://user:secret@api.example.com", allowPrivateCleartext = true)
        assertRejected("http://key@10.0.2.2:8080", allowPrivateCleartext = true)
    }

    private fun assertRejected(raw: String, allowPrivateCleartext: Boolean) {
        try {
            BaseUrlPolicy.normalize(raw, allowPrivateCleartext)
            throw AssertionError("deveria recusar $raw")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message.orEmpty().isNotBlank())
        }
    }
}

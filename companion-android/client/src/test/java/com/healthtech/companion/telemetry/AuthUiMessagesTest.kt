package com.healthtech.companion.telemetry

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AuthUiMessagesTest {

    @Test
    fun `401 and 403 have dedicated copy`() {
        assertEquals(AuthUiMessages.HTTP_401, AuthUiMessages.forHttp(401))
        assertEquals(AuthUiMessages.HTTP_403, AuthUiMessages.forHttp(403))
        assertNull(AuthUiMessages.forHttp(200))
        assertNull(AuthUiMessages.forHttp(500))
    }
}

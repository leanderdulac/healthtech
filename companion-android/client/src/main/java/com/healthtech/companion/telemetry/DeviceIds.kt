package com.healthtech.companion.telemetry

/**
 * Prefixo de [device_id] alinhado a SPRINT_A.md e
 * `docs/openapi/hband-wearable.yaml` (`HBAND-{MAC}`).
 *
 * O módulo histórico `sprint-a` usava `VE30-`; o contrato HTTP é HBAND.
 */
object DeviceIds {
    const val PREFIX = "HBAND-"
    const val UNKNOWN = "HBAND-UNKNOWN"

    fun fromMac(mac: String?): String {
        val raw = mac?.trim().orEmpty()
        if (raw.isBlank()) return UNKNOWN
        val upper = raw.uppercase()
        if (upper.startsWith(PREFIX) || upper.startsWith("GATT-")) return raw
        if (upper.startsWith("VE30-")) {
            return PREFIX + raw.substringAfter('-')
        }
        return PREFIX + raw
    }
}

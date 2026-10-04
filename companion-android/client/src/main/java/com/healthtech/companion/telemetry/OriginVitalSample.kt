package com.healthtech.companion.telemetry

/**
 * Amostra OriginData3 já desacoplada do SDK Veepoo (testável sem AARs).
 */
data class OriginVitalSample(
    val timestampIso: String? = null,
    val heartRate: Double? = null,
    val spo2: Double? = null,
    val bloodPressureSys: Double? = null,
    val bloodPressureDia: Double? = null,
    val hrvRmssd: Double? = null,
    val skinTemp: Double? = null,
    val steps: Int? = null,
)

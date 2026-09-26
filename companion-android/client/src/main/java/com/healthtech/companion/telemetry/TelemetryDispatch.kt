package com.healthtech.companion.telemetry

import com.healthtech.companion.net.dto.WearableIngestRequest

/**
 * Regras de despacho Sprint A/B: **nunca** inventar vitais.
 *
 * O agregador VE30 antigo preenchia HR=72, SpO2=98, temp=33.2, HRV=42
 * quando o sensor ainda não tinha lido nada. O contrato OpenAPI exige
 * `heart_rate` real (20–250); demais campos só entram se houver medição.
 */
object TelemetryDispatch {
    const val HR_MIN = 20.0
    const val HR_MAX = 250.0
    const val SPO2_MIN = 50.0
    const val SPO2_MAX = 100.0
    const val TEMP_MIN = 25.0
    const val TEMP_MAX = 45.0
    const val SYS_MIN = 60.0
    const val SYS_MAX = 260.0
    const val DIA_MIN = 30.0
    const val DIA_MAX = 160.0
    const val HRV_MIN = 0.0
    const val HRV_MAX = 300.0

    fun validHeartRate(bpm: Double?): Double? =
        bpm?.takeIf { it.isFinite() && it in HR_MIN..HR_MAX }

    fun validSpo2(value: Double?): Double? =
        value?.takeIf { it.isFinite() && it in SPO2_MIN..SPO2_MAX }

    fun validSkinTemp(value: Double?): Double? =
        value?.takeIf { it.isFinite() && it in TEMP_MIN..TEMP_MAX }

    fun validSystolic(value: Double?): Double? =
        value?.takeIf { it.isFinite() && it in SYS_MIN..SYS_MAX }

    fun validDiastolic(value: Double?): Double? =
        value?.takeIf { it.isFinite() && it in DIA_MIN..DIA_MAX }

    fun validHrv(value: Double?): Double? =
        value?.takeIf { it.isFinite() && it in HRV_MIN..HRV_MAX }

    /**
     * Monta o POST de ingest. `null` = não despachar (sem FC real).
     */
    fun buildRealtime(
        patientId: String,
        deviceId: String,
        heartRate: Double?,
        spo2: Double? = null,
        skinTemp: Double? = null,
        bloodPressureSys: Double? = null,
        bloodPressureDia: Double? = null,
        hrvRmssd: Double? = null,
        ppgSignal: List<Double>? = null,
        filterType: String = "BMO",
        ingestSource: String = "ble_hband",
        timestamp: String? = null,
    ): WearableIngestRequest? {
        val hr = validHeartRate(heartRate) ?: return null
        val sys = validSystolic(bloodPressureSys)
        val dia = validDiastolic(bloodPressureDia)
        val bpComplete = sys != null && dia != null
        return WearableIngestRequest(
            patientId = patientId,
            deviceId = deviceId,
            heartRate = hr,
            spo2 = validSpo2(spo2),
            skinTemp = validSkinTemp(skinTemp),
            bloodPressureSys = if (bpComplete) sys else null,
            bloodPressureDia = if (bpComplete) dia else null,
            hrvRmssd = validHrv(hrvRmssd),
            ppgSignal = ppgSignal?.takeIf { it.isNotEmpty() },
            filterType = filterType,
            ingestSource = ingestSource,
            timestamp = timestamp,
        )
    }

    fun fromOriginSample(
        sample: OriginVitalSample,
        patientId: String,
        deviceId: String,
        ingestSource: String = "ble_hband",
    ): WearableIngestRequest? = buildRealtime(
        patientId = patientId,
        deviceId = deviceId,
        heartRate = sample.heartRate,
        spo2 = sample.spo2,
        skinTemp = sample.skinTemp,
        bloodPressureSys = sample.bloodPressureSys,
        bloodPressureDia = sample.bloodPressureDia,
        hrvRmssd = sample.hrvRmssd,
        ingestSource = ingestSource,
        timestamp = sample.timestampIso,
    )
}

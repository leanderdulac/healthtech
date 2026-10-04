package com.healthtech.companion.ble

import com.healthtech.companion.telemetry.OriginVitalSample
import com.healthtech.companion.telemetry.TelemetryDispatch
import com.veepoo.protocol.model.datas.HRVOriginData
import com.veepoo.protocol.model.datas.OriginData3
import com.veepoo.protocol.model.datas.TimeData
import java.util.Locale

/**
 * Converte blocos OriginData3 do SDK em [OriginVitalSample] (sem defaults fabricados).
 */
object OriginDataMapper {

    fun toSample(data: OriginData3, hrvByDate: Map<String, Double>): OriginVitalSample {
        val dateKey = data.date ?: data.getmTime()?.toDateKey().orEmpty()
        val spo2 = data.oxygens
            ?.map { it.toDouble() }
            ?.mapNotNull { TelemetryDispatch.validSpo2(it) }
            ?.takeIf { it.isNotEmpty() }
            ?.average()
        val temp = TelemetryDispatch.validSkinTemp(data.temperature)
            ?: TelemetryDispatch.validSkinTemp(data.tempOne.takeIf { it > 0 }?.div(10.0))
        return OriginVitalSample(
            timestampIso = data.getmTime()?.toIsoUtc() ?: dateKey.takeIf { it.isNotBlank() },
            heartRate = TelemetryDispatch.validHeartRate(data.rateValue.toDouble()),
            spo2 = spo2,
            bloodPressureSys = TelemetryDispatch.validSystolic(data.highValue.toDouble()),
            bloodPressureDia = TelemetryDispatch.validDiastolic(data.lowValue.toDouble()),
            hrvRmssd = TelemetryDispatch.validHrv(hrvByDate[dateKey]),
            skinTemp = temp,
            steps = data.stepValue.takeIf { it > 0 },
        )
    }

    fun hrvValue(data: HRVOriginData): Pair<String, Double>? {
        val key = data.date ?: data.getmTime()?.toDateKey() ?: return null
        val hrv = TelemetryDispatch.validHrv(data.hrvValue.toDouble()) ?: return null
        return key to hrv
    }

    private fun TimeData.toIsoUtc(): String {
        val year = if (year in 0..99) 2000 + year else year
        return String.format(
            Locale.US,
            "%04d-%02d-%02dT%02d:%02d:%02dZ",
            year,
            month.coerceIn(1, 12),
            day.coerceIn(1, 31),
            hour.coerceIn(0, 23),
            minute.coerceIn(0, 59),
            second.coerceIn(0, 59),
        )
    }

    private fun TimeData.toDateKey(): String {
        val year = if (year in 0..99) 2000 + year else year
        return String.format(Locale.US, "%04d-%02d-%02d", year, month, day)
    }
}

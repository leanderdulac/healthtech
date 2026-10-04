package com.healthtech.companion.ble

import android.app.Application
import com.healthtech.companion.telemetry.OriginVitalSample
import java.util.concurrent.CopyOnWriteArrayList

/**
 * Dono único do [HbandProtocolClient] (Application-scoped).
 *
 * Activity/ViewModel e [com.healthtech.companion.service.Ve30TelemetryService]
 * compartilham esta sessão — evita dois `VPOperateManager` competindo pelo rádio.
 */
class CompanionSession(app: Application) {

    private val hub = ListenerHub()

    val hband: HbandProtocolClient = HbandProtocolClient(app, hub)

    fun addListener(listener: HbandProtocolClient.Listener) {
        hub.add(listener)
    }

    fun removeListener(listener: HbandProtocolClient.Listener) {
        hub.remove(listener)
    }

    private class ListenerHub : HbandProtocolClient.Listener {
        private val listeners = CopyOnWriteArrayList<HbandProtocolClient.Listener>()

        fun add(listener: HbandProtocolClient.Listener) {
            listeners.addIfAbsent(listener)
        }

        fun remove(listener: HbandProtocolClient.Listener) {
            listeners.remove(listener)
        }

        override fun onScanStarted() = listeners.forEach { it.onScanStarted() }
        override fun onDeviceFound(device: ScannedDevice) = listeners.forEach { it.onDeviceFound(device) }
        override fun onScanFinished() = listeners.forEach { it.onScanFinished() }
        override fun onStatus(message: String) = listeners.forEach { it.onStatus(message) }
        override fun onReady(mac: String) = listeners.forEach { it.onReady(mac) }
        override fun onHeartRate(bpm: Int, mac: String, status: String) =
            listeners.forEach { it.onHeartRate(bpm, mac, status) }
        override fun onSpo2(percent: Int, mac: String) = listeners.forEach { it.onSpo2(percent, mac) }
        override fun onPpgSample(sample: Double) = listeners.forEach { it.onPpgSample(sample) }
        override fun onDisconnected(mac: String, reason: String?) =
            listeners.forEach { it.onDisconnected(mac, reason) }
        override fun onError(message: String) = listeners.forEach { it.onError(message) }
        override fun onOriginProgress(day: Int, date: String, samples: Int) =
            listeners.forEach { it.onOriginProgress(day, date, samples) }
        override fun onOriginComplete(samples: List<OriginVitalSample>) =
            listeners.forEach { it.onOriginComplete(samples) }
        override fun onOriginError(message: String) = listeners.forEach { it.onOriginError(message) }
    }
}

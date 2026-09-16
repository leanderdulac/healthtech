package com.healthtech.companion.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.healthtech.companion.HealthtechApp
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Foreground service que **não** cria um segundo stack BLE.
 *
 * A Activity/ViewModel usa [com.healthtech.companion.ble.CompanionSession]
 * (Application). Este service só mantém o processo vivo (Doze) enquanto
 * houver sessão autenticada / medição.
 */
class Ve30TelemetryService : Service() {

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        running.set(true)
        Log.i(TAG, "Ve30TelemetryService criado (session=${(application as HealthtechApp).session.hband.connectedMac})")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val mac = intent?.getStringExtra(EXTRA_MAC)
        val text = if (mac.isNullOrBlank()) {
            "Monitoramento fisiológico ativo."
        } else {
            "Conectado $mac"
        }
        val notification = buildNotification("Healthtech Companion", text)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        running.set(false)
        Log.i(TAG, "Ve30TelemetryService destruído")
        super.onDestroy()
    }

    private fun buildNotification(title: String, content: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(content)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Telemetria da pulseira",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Mantém a coleta BLE ativa com a tela desligada"
            }
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.createNotificationChannel(channel)
        }
    }

    companion object {
        private const val TAG = "Ve30TelemetryService"
        const val CHANNEL_ID = "healthtech_hband_channel"
        const val NOTIFICATION_ID = 1001
        const val EXTRA_MAC = "extra_mac_address"

        private val running = AtomicBoolean(false)

        val isRunning: Boolean get() = running.get()

        fun start(context: Context, mac: String?) {
            val intent = Intent(context, Ve30TelemetryService::class.java).apply {
                putExtra(EXTRA_MAC, mac)
            }
            ContextCompat.startForegroundService(context, intent)
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, Ve30TelemetryService::class.java))
        }

        fun updateVitals(context: Context, bpm: Int, spo2: Int?) {
            if (!isRunning) return
            val spo2Part = spo2?.let { " · SpO2 $it%" } ?: ""
            val notification = NotificationCompat.Builder(context, CHANNEL_ID)
                .setContentTitle("Healthtech Companion")
                .setContentText("FC $bpm bpm$spo2Part")
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .setOngoing(true)
                .setSilent(true)
                .build()
            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.notify(NOTIFICATION_ID, notification)
        }
    }
}

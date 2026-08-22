package com.healthtech.companion.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import com.healthtech.companion.BuildConfig
import com.healthtech.companion.ble.HbandConnectionManager
import com.healthtech.companion.ble.HbandRealtimeCollector
import com.healthtech.companion.net.HealthtechApiClient

/**
 * Foreground Service 24/7 para Monitoramento Contínuo do Relógio VE30.
 * 
 * Garante que a coleta BLE e o envio de telemetria para a IA permaneçam ativos
 * mesmo com o aplicativo em segundo plano ou aparelho em repouso (Doze Mode).
 */
class Ve30TelemetryService : Service() {

    inner class LocalBinder : Binder() {
        fun getService(): Ve30TelemetryService = this@Ve30TelemetryService
    }

    private val binder = LocalBinder()
    lateinit var connectionManager: HbandConnectionManager
    lateinit var apiClient: HealthtechApiClient
    lateinit var collector: HbandRealtimeCollector

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "Criando Ve30TelemetryService...")
        createNotificationChannel()

        connectionManager = HbandConnectionManager(applicationContext)
        apiClient = HealthtechApiClient(
            appContext = applicationContext,
            baseUrl = BuildConfig.HEALTHTECH_BASE_URL,
            apiKey = BuildConfig.HEALTHTECH_INGEST_API_KEY,
        )
        collector = HbandRealtimeCollector(connectionManager, apiClient, BuildConfig.HEALTHTECH_PATIENT_ID)

        connectionManager.initSdk()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val notification = buildNotification("VE30 Conectado", "Monitoramento fisiológico contínuo ativo.")
        startForeground(NOTIFICATION_ID, notification)

        val targetMac = intent?.getStringExtra(EXTRA_MAC)
        if (!targetMac.isNullOrBlank() && !connectionManager.isConnected) {
            connectionManager.connect(targetMac)
        }

        return START_STICKY
    }

    fun updateNotificationVitals(bpm: Double, spo2: Double, bp: String) {
        val text = "FC: ${bpm.toInt()} bpm | SpO2: ${spo2.toInt()}% | PA: $bp"
        val notification = buildNotification("VE30 Monitorando", text)
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(NOTIFICATION_ID, notification)
    }

    private fun buildNotification(title: String, content: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(content)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "HealthTech VE30 Telemetria",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Notificação de serviço contínuo de telemetria do relógio VE30"
            }
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.createNotificationChannel(channel)
        }
    }

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onDestroy() {
        super.onDestroy()
        Log.i(TAG, "Destruindo Ve30TelemetryService...")
        collector.stopAllSensors()
        connectionManager.disconnect()
    }

    companion object {
        private const val TAG = "Ve30TelemetryService"
        const val CHANNEL_ID = "healthtech_ve30_channel"
        const val NOTIFICATION_ID = 1001
        const val EXTRA_MAC = "extra_mac_address"
    }
}
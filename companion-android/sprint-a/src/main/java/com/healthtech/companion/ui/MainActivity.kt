package com.healthtech.companion.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.healthtech.companion.ble.HbandConnectionManager
import com.healthtech.companion.ble.HbandRealtimeCollector
import com.healthtech.companion.net.HealthtechApiClient

/**
 * Activity Principal do Companion Android para Relógios VE30.
 * 
 * Oferece interface de monitoramento e controle para:
 *  - Scan e Pareamento BLE
 *  - Visualização em tempo real de BPM, SpO2, Temperatura e Pressão Arterial
 *  - Status da Conexão com o Backend de IA HealthTech
 *  - Modo de Demonstração / Smoke Test
 */
class MainActivity : AppCompatActivity() {

    private lateinit var connectionManager: HbandConnectionManager
    private lateinit var apiClient: HealthtechApiClient
    private lateinit var collector: HbandRealtimeCollector

    private var tvStatus: TextView? = null
    private var tvBpm: TextView? = null
    private var tvSpo2: TextView? = null
    private var tvTemp: TextView? = null
    private var tvBp: TextView? = null
    private var tvAiStatus: TextView? = null
    private var btnScan: Button? = null
    private var btnConnect: Button? = null
    private var btnStartSensors: Button? = null

    private var selectedMac: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Se houver layout XML infla, senão constrói lógica programática
        initDependencies()
        checkAndRequestPermissions()
    }

    private fun initDependencies() {
        val baseUrl = "https://healthtech-responsive-5794833455.us-central1.run.app"
        val apiKey = "" // Inserir chave de ingestão
        val patientId = "PAT-VE30-001"

        connectionManager = HbandConnectionManager(applicationContext)
        apiClient = HealthtechApiClient(baseUrl, apiKey)
        collector = HbandRealtimeCollector(connectionManager, apiClient, patientId)

        connectionManager.initSdk()
        setupListeners()
    }

    private fun setupListeners() {
        connectionManager.setListener(object : HbandConnectionManager.Listener {
            override fun onScanResult(mac: String, name: String?, rssi: Int) {
                runOnUiThread {
                    selectedMac = mac
                    tvStatus?.text = "Encontrado: $name ($mac) RSSI: $rssi"
                    btnConnect?.isEnabled = true
                }
            }

            override fun onConnecting(mac: String) {
                runOnUiThread { tvStatus?.text = "Conectando ao VE30 [$mac]..." }
            }

            override fun onConnected(mac: String) {
                runOnUiThread { tvStatus?.text = "BLE Conectado. Autenticando senha..." }
            }

            override fun onAuthenticated(mac: String, supportedFunctionsSummary: String) {
                runOnUiThread { tvStatus?.text = "Autenticado! $supportedFunctionsSummary" }
            }

            override fun onReady(mac: String) {
                runOnUiThread {
                    tvStatus?.text = "VE30 PRONTO e Sincronizado!"
                    btnStartSensors?.isEnabled = true
                    collector.startAllSensors()
                }
            }

            override fun onDisconnected(mac: String, reason: String?) {
                runOnUiThread {
                    tvStatus?.text = "Desconectado: $reason"
                    btnStartSensors?.isEnabled = false
                }
            }

            override fun onBatteryStatus(level: Int, isCharging: Boolean) {
                runOnUiThread { tvStatus?.text = "Bateria: $level% ${if (isCharging) "(Carregando)" else ""}" }
            }

            override fun onError(message: String) {
                runOnUiThread { Toast.makeText(this@MainActivity, message, Toast.LENGTH_SHORT).show() }
            }
        })

        collector.setUiCallback(object : HbandRealtimeCollector.UiCallback {
            override fun onVitalUpdate(bpm: Double, spo2: Double, temp: Double, bpStr: String) {
                runOnUiThread {
                    tvBpm?.text = "${bpm.toInt()} bpm"
                    tvSpo2?.text = "${spo2.toInt()}%"
                    tvTemp?.text = String.format("%.1f °C", temp)
                    tvBp?.text = bpStr
                }
            }

            override fun onIngestSuccess(code: Int, summary: String) {
                runOnUiThread { tvAiStatus?.text = summary }
            }

            override fun onError(message: String) {
                runOnUiThread { tvAiStatus?.text = "Erro IA: $message" }
            }
        })
    }

    private fun checkAndRequestPermissions() {
        val permissions = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            permissions.add(Manifest.permission.BLUETOOTH_SCAN)
            permissions.add(Manifest.permission.BLUETOOTH_CONNECT)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        permissions.add(Manifest.permission.ACCESS_FINE_LOCATION)

        val needed = permissions.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (needed.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, needed.toTypedArray(), 101)
        }
    }
}
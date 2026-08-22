package com.healthtech.companion.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.healthtech.companion.BuildConfig
import com.healthtech.companion.ble.HbandConnectionManager
import com.healthtech.companion.ble.HbandRealtimeCollector
import com.healthtech.companion.databinding.ActivityMainBinding
import com.healthtech.companion.net.HealthtechApiClient

/**
 * Activity Principal do Companion Android para Relógios VE30.
 *
 * Integração completa com o backend HealthTech via BLE e HTTP/REST.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding

    private lateinit var connectionManager: HbandConnectionManager
    private lateinit var apiClient: HealthtechApiClient
    private lateinit var collector: HbandRealtimeCollector

    private var selectedMac: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.btnConnect.isEnabled = false
        binding.btnStartSensors.isEnabled = false

        initDependencies()
        setupClickListeners()
        setupSdkListeners()
        checkAndRequestPermissions()
    }

    private fun initDependencies() {
        connectionManager = HbandConnectionManager(applicationContext)
        apiClient = HealthtechApiClient(
            appContext = applicationContext,
            baseUrl = BuildConfig.HEALTHTECH_BASE_URL,
            apiKey = BuildConfig.HEALTHTECH_INGEST_API_KEY,
        )
        collector = HbandRealtimeCollector(connectionManager, apiClient, BuildConfig.HEALTHTECH_PATIENT_ID)

        connectionManager.initSdk()
    }

    private fun setupClickListeners() {
        binding.btnScan.setOnClickListener {
            binding.tvStatus.text = "Buscando relógios VE30 próximos..."
            connectionManager.startScan()
        }

        binding.btnConnect.setOnClickListener {
            val mac = selectedMac ?: "E4:65:08:VE:30:01"
            binding.tvStatus.text = "Conectando ao VE30 [$mac]..."
            connectionManager.connect(mac)
        }

        binding.btnStartSensors.setOnClickListener {
            binding.tvStatus.text = "Streaming contínuo de sensores ativado."
            collector.startAllSensors()
        }
    }

    private fun setupSdkListeners() {
        connectionManager.setListener(object : HbandConnectionManager.Listener {
            override fun onScanResult(mac: String, name: String?, rssi: Int) {
                runOnUiThread {
                    selectedMac = mac
                    binding.tvStatus.text = "Encontrado: $name ($mac) RSSI: $rssi"
                    binding.btnConnect.isEnabled = true
                }
            }

            override fun onConnecting(mac: String) {
                runOnUiThread { binding.tvStatus.text = "Conectando ao VE30 [$mac]..." }
            }

            override fun onConnected(mac: String) {
                runOnUiThread { binding.tvStatus.text = "BLE Conectado. Autenticando senha..." }
            }

            override fun onAuthenticated(mac: String, supportedFunctionsSummary: String) {
                runOnUiThread { binding.tvStatus.text = "Autenticado! $supportedFunctionsSummary" }
            }

            override fun onReady(mac: String) {
                runOnUiThread {
                    binding.tvStatus.text = "VE30 PRONTO e Sincronizado!"
                    binding.btnStartSensors.isEnabled = true
                    collector.startAllSensors()
                }
            }

            override fun onDisconnected(mac: String, reason: String?) {
                runOnUiThread {
                    binding.tvStatus.text = "Desconectado: $reason"
                    binding.btnStartSensors.isEnabled = false
                }
            }

            override fun onBatteryStatus(level: Int, isCharging: Boolean) {
                runOnUiThread { binding.tvStatus.text = "Bateria: $level% ${if (isCharging) "(Carregando)" else ""}" }
            }

            override fun onError(message: String) {
                runOnUiThread { Toast.makeText(this@MainActivity, message, Toast.LENGTH_SHORT).show() }
            }
        })

        collector.setUiCallback(object : HbandRealtimeCollector.UiCallback {
            override fun onVitalUpdate(bpm: Double, spo2: Double, temp: Double, bpStr: String) {
                runOnUiThread {
                    binding.tvBpm.text = "${bpm.toInt()} bpm"
                    binding.tvSpo2.text = "${spo2.toInt()}%"
                    binding.tvTemp.text = String.format("%.1f °C", temp)
                    binding.tvBp.text = bpStr
                }
            }

            override fun onIngestSuccess(code: Int, summary: String) {
                runOnUiThread { binding.tvAiStatus.text = summary }
            }

            override fun onError(message: String) {
                runOnUiThread { binding.tvAiStatus.text = "Alerta/Erro IA: $message" }
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

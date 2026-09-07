package com.healthtech.companion.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.healthtech.companion.ble.BlePermissions
import com.healthtech.companion.ble.BleTransport
import com.healthtech.companion.ble.GattHeartRateClient
import com.healthtech.companion.ble.HbandProtocolClient
import com.healthtech.companion.ble.ScannedDevice
import com.healthtech.companion.ble.SimulatedBleTransport
import com.healthtech.companion.data.AppPrefs
import com.healthtech.companion.net.ApiResult
import com.healthtech.companion.net.HealthtechRepository
import com.healthtech.companion.net.dto.ProcessedTelemetry
import com.healthtech.companion.net.dto.WearableIngestRequest
import com.healthtech.companion.net.outbox.OutboxFlusher
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class UiState(
    val baseUrl: String = "",
    val ingestApiKey: String = "",
    val patientId: String = "",
    val deviceId: String = "",
    val heartRateInput: String = "78",
    val busy: Boolean = false,
    val apiOnline: Boolean? = null,
    val statusLine: String = "Configure a API key e toque em Testar conexão.",
    val lastIngest: ProcessedTelemetry? = null,
    val latest: ProcessedTelemetry? = null,
    val historyPreview: String = "",
    val outboxPending: Int = 0,
    val showKey: Boolean = false,
    val bleSimRunning: Boolean = false,
    val lastSimBpm: Double? = null,
    val scanning: Boolean = false,
    val scannedDevices: List<ScannedDevice> = emptyList(),
    val connectedMac: String? = null,
    val handshakeReady: Boolean = false,
    val lastLiveBpm: Int? = null,
    val lastSpo2: Int? = null,
    val measuring: Boolean = false,
)

class MainViewModel(app: Application) : AndroidViewModel(app) {

    private val prefs = AppPrefs(app)

    private val _state = MutableStateFlow(
        UiState(
            baseUrl = prefs.baseUrl,
            ingestApiKey = prefs.ingestApiKey,
            patientId = prefs.patientId,
            deviceId = prefs.deviceId,
        ),
    )
    val state: StateFlow<UiState> = _state.asStateFlow()

    private var repository: HealthtechRepository = buildRepo()
    private var outbox: OutboxFlusher = OutboxFlusher(repository)
    private var bleSim: BleTransport? = null
    private var gattHr: GattHeartRateClient? = null
    private val hband = HbandProtocolClient(
        app,
        object : HbandProtocolClient.Listener {
            override fun onScanStarted() {
                _state.update {
                    it.copy(scanning = true, scannedDevices = emptyList(), statusLine = "Escaneando BLE…")
                }
            }

            override fun onDeviceFound(device: ScannedDevice) {
                _state.update { s ->
                    val next = (s.scannedDevices.filterNot { it.mac == device.mac } + device)
                        .sortedWith(
                            compareByDescending<ScannedDevice> { it.wearableLikely }
                                .thenByDescending { it.rssi },
                        )
                        .take(24)
                    s.copy(scannedDevices = next)
                }
            }

            override fun onScanFinished() {
                _state.update {
                    it.copy(
                        scanning = false,
                        statusLine = "Scan ok. Pulseiras no topo — evite fone/TV/caixa.",
                    )
                }
            }

            override fun onStatus(message: String) {
                _state.update { it.copy(statusLine = message) }
            }

            override fun onReady(mac: String) {
                _state.update {
                    it.copy(
                        handshakeReady = true,
                        connectedMac = mac,
                        deviceId = "HBAND-$mac",
                        measuring = true,
                        statusLine = "Handshake ok. Medindo FC…",
                    )
                }
                prefs.deviceId = "HBAND-$mac"
            }

            override fun onHeartRate(bpm: Int, mac: String, status: String) {
                ingestLive(bpm, "HBAND-$mac", "ble_hband")
                _state.update {
                    it.copy(
                        lastLiveBpm = bpm,
                        lastSimBpm = bpm.toDouble(),
                        heartRateInput = bpm.toString(),
                        measuring = true,
                    )
                }
            }

            override fun onSpo2(percent: Int, mac: String) {
                _state.update { it.copy(lastSpo2 = percent, statusLine = "SpO2 $percent%") }
            }

            override fun onDisconnected(mac: String, reason: String?) {
                _state.update {
                    it.copy(
                        handshakeReady = false,
                        connectedMac = null,
                        measuring = false,
                        statusLine = "Desconectado${reason?.let { r -> ": $r" } ?: ""}",
                    )
                }
            }

            override fun onError(message: String) {
                _state.update { it.copy(statusLine = message, measuring = false) }
            }
        },
    )

    private fun buildRepo(): HealthtechRepository {
        val s = _state.value
        return HealthtechRepository.create(
            baseUrl = s.baseUrl.ifBlank { prefs.baseUrl },
            apiKey = s.ingestApiKey,
            enableHttpLogging = true,
        )
    }

    private fun rebuildClients() {
        repository = buildRepo()
        outbox = OutboxFlusher(repository)
    }

    fun onBaseUrlChange(v: String) = _state.update { it.copy(baseUrl = v) }
    fun onApiKeyChange(v: String) = _state.update { it.copy(ingestApiKey = v) }
    fun onPatientIdChange(v: String) = _state.update { it.copy(patientId = v) }
    fun onDeviceIdChange(v: String) = _state.update { it.copy(deviceId = v) }
    fun onHeartRateChange(v: String) = _state.update { it.copy(heartRateInput = v) }
    fun toggleShowKey() = _state.update { it.copy(showKey = !it.showKey) }

    fun saveSettings() {
        val s = _state.value
        prefs.baseUrl = s.baseUrl
        prefs.ingestApiKey = s.ingestApiKey
        prefs.patientId = s.patientId
        prefs.deviceId = s.deviceId
        rebuildClients()
        _state.update {
            it.copy(
                baseUrl = prefs.baseUrl,
                statusLine = "Configuração salva.",
            )
        }
    }

    fun checkHealth() {
        saveSettings()
        viewModelScope.launch {
            _state.update { it.copy(busy = true, statusLine = "Testando /api/health…") }
            when (val r = repository.health()) {
                is ApiResult.Success -> {
                    val body = r.data
                    _state.update {
                        it.copy(
                            busy = false,
                            apiOnline = true,
                            statusLine = "API online: ${body.service ?: "ok"} v${body.version ?: "?"} (${r.httpCode})",
                        )
                    }
                }
                is ApiResult.Failure -> {
                    _state.update {
                        it.copy(
                            busy = false,
                            apiOnline = false,
                            statusLine = "Falha health (${r.httpCode}): ${r.message}",
                        )
                    }
                }
            }
        }
    }

    fun sendHeartRate() {
        saveSettings()
        val s = _state.value
        val bpm = s.heartRateInput.toDoubleOrNull()
        if (bpm == null || bpm < 20 || bpm > 250) {
            _state.update { it.copy(statusLine = "BPM inválido (20–250).") }
            return
        }
        if (s.ingestApiKey.isBlank()) {
            _state.update { it.copy(statusLine = "Defina a API key (escopo wearables:write).") }
            return
        }

        val req = WearableIngestRequest(
            patientId = s.patientId,
            deviceId = s.deviceId,
            heartRate = bpm,
            filterType = "BMO",
            ingestSource = "companion_manual",
        )

        viewModelScope.launch {
            _state.update { it.copy(busy = true, statusLine = "Enviando ingest…") }
            when (val r = repository.ingest(req)) {
                is ApiResult.Success -> {
                    _state.update {
                        it.copy(
                            busy = false,
                            lastIngest = r.data,
                            statusLine = "Ingest OK (${r.httpCode}) patient=${r.data.patientId}",
                        )
                    }
                }
                is ApiResult.Failure -> {
                    if (r.isRetryable) {
                        outbox.enqueue(req)
                        _state.update {
                            it.copy(
                                busy = false,
                                outboxPending = outbox.pending().size,
                                statusLine = "Rede/servidor (${r.httpCode}). Guardado na outbox: ${r.message}",
                            )
                        }
                    } else {
                        _state.update {
                            it.copy(
                                busy = false,
                                statusLine = failLabel(r),
                            )
                        }
                    }
                }
            }
        }
    }

    fun enqueueAndFlush() {
        saveSettings()
        val s = _state.value
        val bpm = s.heartRateInput.toDoubleOrNull() ?: 78.0
        outbox.enqueue(
            WearableIngestRequest(
                patientId = s.patientId,
                deviceId = s.deviceId,
                heartRate = bpm,
                filterType = "BMO",
                ingestSource = "companion_manual",
            ),
        )
        viewModelScope.launch {
            _state.update { it.copy(busy = true, statusLine = "Flush outbox…") }
            val summary = outbox.flush(preferBatch = true)
            _state.update {
                it.copy(
                    busy = false,
                    outboxPending = outbox.pending().size,
                    statusLine = "Outbox: sent=${summary.sent} dead=${summary.dead} retry=${summary.failed} auth=${summary.authFailures}",
                )
            }
        }
    }

    fun loadLatest() {
        saveSettings()
        val patientId = _state.value.patientId
        viewModelScope.launch {
            _state.update { it.copy(busy = true, statusLine = "Buscando latest…") }
            when (val r = repository.latest(patientId)) {
                is ApiResult.Success -> {
                    _state.update {
                        it.copy(
                            busy = false,
                            latest = r.data,
                            statusLine = "Latest OK — HR clean=${r.data.cleanedTelemetry?.get("heart_rate_clean") ?: "—"}",
                        )
                    }
                }
                is ApiResult.Failure -> {
                    _state.update {
                        it.copy(busy = false, statusLine = failLabel(r), latest = null)
                    }
                }
            }
        }
    }

    fun loadHistory() {
        saveSettings()
        val patientId = _state.value.patientId
        viewModelScope.launch {
            _state.update { it.copy(busy = true, statusLine = "Buscando history…") }
            when (val r = repository.history(patientId, limit = 10)) {
                is ApiResult.Success -> {
                    val records = r.data.records.orEmpty()
                    val preview = records.take(5).joinToString("\n") { rec ->
                        val hr = rec.cleanedTelemetry?.get("heart_rate_clean")
                            ?: rec.rawTelemetry?.get("heart_rate")
                            ?: "—"
                        "${rec.timestamp ?: "?"}  HR=$hr"
                    }.ifBlank { "(vazio)" }
                    _state.update {
                        it.copy(
                            busy = false,
                            historyPreview = "total=${r.data.totalRecords}\n$preview",
                            statusLine = "History OK (${records.size} registros)",
                        )
                    }
                }
                is ApiResult.Failure -> {
                    _state.update {
                        it.copy(busy = false, statusLine = failLabel(r), historyPreview = "")
                    }
                }
            }
        }
    }

    fun smokeHeart() {
        saveSettings()
        viewModelScope.launch {
            _state.update { it.copy(busy = true, statusLine = "Smoke HR…") }
            val s = _state.value
            when (val r = repository.smokeHeart(s.patientId, s.deviceId, 78.0)) {
                is ApiResult.Success -> {
                    _state.update {
                        it.copy(
                            busy = false,
                            lastIngest = r.data,
                            statusLine = "Smoke OK (${r.httpCode})",
                        )
                    }
                }
                is ApiResult.Failure -> {
                    _state.update { it.copy(busy = false, statusLine = failLabel(r)) }
                }
            }
        }
    }

    fun startScan() {
        saveSettings()
        if (!BlePermissions.granted(getApplication())) {
            _state.update {
                it.copy(statusLine = "Permissões Bluetooth/Localização necessárias para o scan.")
            }
            return
        }
        runCatching { hband.initSdk() }
        hband.startScan()
    }

    fun stopScan() {
        hband.stopScan()
        _state.update { it.copy(scanning = false) }
    }

    fun connectDevice(device: ScannedDevice) {
        saveSettings()
        hband.stopScan()
        gattHr?.close()
        _state.update {
            it.copy(
                scanning = false,
                connectedMac = device.mac,
                handshakeReady = false,
                lastLiveBpm = null,
                statusLine = "Conectando ${device.label}…",
            )
        }
        hband.connect(device.mac, device.name.takeIf { it != "N/A" })
    }

    fun disconnectDevice() {
        hband.disconnect()
        gattHr?.close()
        _state.update {
            it.copy(
                connectedMac = null,
                handshakeReady = false,
                measuring = false,
                statusLine = "Desconectado.",
            )
        }
    }

    fun tryGattFallback() {
        val mac = _state.value.connectedMac ?: return
        hband.stopHeart()
        if (gattHr == null) {
            gattHr = GattHeartRateClient(
                getApplication(),
                onStatus = { msg -> _state.update { it.copy(statusLine = msg) } },
                onBpm = { bpm, addr ->
                    ingestLive(bpm, "GATT-$addr", "ble_hband")
                    _state.update {
                        it.copy(lastLiveBpm = bpm, heartRateInput = bpm.toString(), measuring = true)
                    }
                },
                onDisconnected = { _state.update { it.copy(measuring = false, handshakeReady = false) } },
            )
        }
        gattHr?.connect(mac)
    }

    fun toggleBleSimulator() {
        saveSettings()
        if (bleSim?.isRunning == true) {
            bleSim?.stop()
            bleSim = null
            _state.update { it.copy(bleSimRunning = false, statusLine = "Simulador BLE parado.") }
            return
        }
        val s = _state.value
        if (s.ingestApiKey.isBlank()) {
            _state.update { it.copy(statusLine = "Defina a API key antes de simular BLE.") }
            return
        }
        val transport = SimulatedBleTransport(
            scope = viewModelScope,
            deviceId = s.deviceId.ifBlank { "HBAND-SIM-001" },
            listener = { bpm, deviceId, source ->
                _state.update { it.copy(lastSimBpm = bpm, heartRateInput = bpm.toInt().toString()) }
                viewModelScope.launch {
                    val current = _state.value
                    val req = WearableIngestRequest(
                        patientId = current.patientId,
                        deviceId = deviceId,
                        heartRate = bpm,
                        filterType = "BMO",
                        ingestSource = source,
                    )
                    when (val r = repository.ingest(req)) {
                        is ApiResult.Success -> _state.update {
                            it.copy(
                                lastIngest = r.data,
                                statusLine = "BLE sim ${bpm.toInt()} bpm → ingest ${r.httpCode}",
                            )
                        }
                        is ApiResult.Failure -> {
                            if (r.isRetryable) outbox.enqueue(req)
                            _state.update { it.copy(statusLine = failLabel(r)) }
                        }
                    }
                }
            },
            status = { msg -> _state.update { it.copy(statusLine = msg) } },
        )
        bleSim = transport
        transport.start()
        _state.update { it.copy(bleSimRunning = true) }
    }

    fun tryHbandSdk() {
        startScan()
    }

    private var lastIngestAt = 0L

    private fun ingestLive(bpm: Int, deviceId: String, source: String) {
        val now = System.currentTimeMillis()
        if (now - lastIngestAt < 3_000) return
        lastIngestAt = now
        val s = _state.value
        if (s.ingestApiKey.isBlank()) return
        viewModelScope.launch {
            val req = WearableIngestRequest(
                patientId = s.patientId,
                deviceId = deviceId,
                heartRate = bpm.toDouble(),
                spo2 = s.lastSpo2?.toDouble(),
                filterType = "BMO",
                ingestSource = source,
            )
            when (val r = repository.ingest(req)) {
                is ApiResult.Success -> _state.update {
                    it.copy(lastIngest = r.data, statusLine = "FC $bpm bpm → ingest ${r.httpCode}")
                }
                is ApiResult.Failure -> {
                    if (r.isRetryable) outbox.enqueue(req)
                    _state.update { it.copy(statusLine = failLabel(r)) }
                }
            }
        }
    }

    override fun onCleared() {
        bleSim?.stop()
        hband.disconnect()
        gattHr?.close()
        super.onCleared()
    }

    private fun failLabel(r: ApiResult.Failure): String = buildString {
        append("Erro ${r.httpCode}: ${r.message}")
        if (r.isUnauthorized) append(" — confira API key / escopo")
        if (r.isValidationError) append(" — payload inválido (não reenviar)")
        if (r.isRateLimited) append(" — rate limit; aguarde")
        r.requestId?.let { append(" [req=$it]") }
    }
}

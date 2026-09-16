package com.healthtech.companion.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.healthtech.companion.HealthtechApp
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
import com.healthtech.companion.service.Ve30TelemetryService
import com.healthtech.companion.telemetry.AuthUiMessages
import com.healthtech.companion.telemetry.DeviceIds
import com.healthtech.companion.telemetry.OriginVitalSample
import com.healthtech.companion.telemetry.PpgBuffer
import com.healthtech.companion.telemetry.TelemetryDispatch
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
    val authError: String? = null,
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
    val historySyncing: Boolean = false,
    val historySyncLine: String = "",
)

class MainViewModel(app: Application) : AndroidViewModel(app), HbandProtocolClient.Listener {

    private val prefs = AppPrefs(app)
    private val session = (app as HealthtechApp).session
    private val hband = session.hband
    private val ppgBuffer = PpgBuffer()

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

    init {
        session.addListener(this)
    }

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
        val deviceId = DeviceIds.fromMac(mac)
        _state.update {
            it.copy(
                handshakeReady = true,
                connectedMac = mac,
                deviceId = deviceId,
                measuring = true,
                statusLine = "Handshake ok. Medindo FC…",
            )
        }
        prefs.deviceId = deviceId
        runCatching { Ve30TelemetryService.start(getApplication(), mac) }
            .onFailure { err ->
                _state.update {
                    it.copy(statusLine = "Handshake ok. Serviço em 1º plano falhou: ${err.message}")
                }
            }
    }

    override fun onHeartRate(bpm: Int, mac: String, status: String) {
        ingestLive(bpm, DeviceIds.fromMac(mac), "ble_hband")
        _state.update {
            it.copy(
                lastLiveBpm = bpm,
                lastSimBpm = bpm.toDouble(),
                heartRateInput = bpm.toString(),
                measuring = true,
            )
        }
        Ve30TelemetryService.updateVitals(getApplication(), bpm, _state.value.lastSpo2)
    }

    override fun onSpo2(percent: Int, mac: String) {
        _state.update { it.copy(lastSpo2 = percent, statusLine = "SpO2 $percent%") }
    }

    override fun onPpgSample(sample: Double) {
        ppgBuffer.append(sample)
    }

    override fun onDisconnected(mac: String, reason: String?) {
        Ve30TelemetryService.stop(getApplication())
        _state.update {
            it.copy(
                handshakeReady = false,
                connectedMac = null,
                measuring = false,
                historySyncing = false,
                statusLine = "Desconectado${reason?.let { r -> ": $r" } ?: ""}",
            )
        }
    }

    override fun onError(message: String) {
        _state.update { it.copy(statusLine = message, measuring = false) }
    }

    override fun onOriginProgress(day: Int, date: String, samples: Int) {
        _state.update {
            it.copy(
                historySyncing = true,
                historySyncLine = "OriginData3 dia $day ($date) — $samples blocos…",
                statusLine = "Sincronizando histórico… $samples blocos",
            )
        }
    }

    override fun onOriginComplete(samples: List<OriginVitalSample>) {
        viewModelScope.launch { flushOriginSamples(samples) }
    }

    override fun onOriginError(message: String) {
        _state.update {
            it.copy(
                busy = false,
                historySyncing = false,
                historySyncLine = message,
                statusLine = message,
            )
        }
    }

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
    fun onApiKeyChange(v: String) = _state.update { it.copy(ingestApiKey = v, authError = null) }
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
            _state.update { it.copy(busy = true, statusLine = "Testando /api/health…", authError = null) }
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
                is ApiResult.Failure -> applyFailure(r, "Falha health")
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

        val req = TelemetryDispatch.buildRealtime(
            patientId = s.patientId,
            deviceId = DeviceIds.fromMac(s.deviceId),
            heartRate = bpm,
            ingestSource = "companion_manual",
        ) ?: run {
            _state.update { it.copy(statusLine = "BPM inválido — nada enviado.") }
            return
        }

        viewModelScope.launch { ingestRequest(req, "Enviando ingest…") }
    }

    fun enqueueAndFlush() {
        saveSettings()
        val s = _state.value
        val req = TelemetryDispatch.buildRealtime(
            patientId = s.patientId,
            deviceId = DeviceIds.fromMac(s.deviceId),
            heartRate = s.heartRateInput.toDoubleOrNull(),
            ingestSource = "companion_manual",
        )
        if (req == null) {
            _state.update {
                it.copy(statusLine = "Outbox: informe um BPM real (20–250) — não enfileiramos vitais fabricados.")
            }
            return
        }
        outbox.enqueue(req)
        viewModelScope.launch {
            _state.update { it.copy(busy = true, statusLine = "Flush outbox…") }
            val summary = outbox.flush(preferBatch = true)
            _state.update {
                it.copy(
                    busy = false,
                    outboxPending = outbox.pending().size,
                    statusLine = "Outbox: sent=${summary.sent} dead=${summary.dead} retry=${summary.failed} auth=${summary.authFailures}",
                    authError = if (summary.authFailures > 0) {
                        "Falha de autenticação na outbox (401/403). Confira a API key e o escopo wearables:write."
                    } else {
                        it.authError
                    },
                )
            }
        }
    }

    fun loadLatest() {
        saveSettings()
        val patientId = _state.value.patientId
        viewModelScope.launch {
            _state.update { it.copy(busy = true, statusLine = "Buscando latest…", authError = null) }
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
                is ApiResult.Failure -> applyFailure(r)
            }
        }
    }

    fun loadHistory() {
        saveSettings()
        val patientId = _state.value.patientId
        viewModelScope.launch {
            _state.update { it.copy(busy = true, statusLine = "Buscando history…", authError = null) }
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
                is ApiResult.Failure -> applyFailure(r)
            }
        }
    }

    fun smokeHeart() {
        saveSettings()
        viewModelScope.launch {
            _state.update { it.copy(busy = true, statusLine = "Smoke HR…", authError = null) }
            val s = _state.value
            when (val r = repository.smokeHeart(s.patientId, DeviceIds.fromMac(s.deviceId), 78.0)) {
                is ApiResult.Success -> {
                    _state.update {
                        it.copy(
                            busy = false,
                            lastIngest = r.data,
                            statusLine = "Smoke OK (${r.httpCode})",
                        )
                    }
                }
                is ApiResult.Failure -> applyFailure(r)
            }
        }
    }

    fun startScan() {
        saveSettings()
        if (!BlePermissions.bleGranted(getApplication())) {
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
                authError = null,
            )
        }
        hband.connect(device.mac, device.name.takeIf { it != "N/A" })
    }

    fun disconnectDevice() {
        hband.stopAllSensors()
        hband.disconnect()
        gattHr?.close()
        Ve30TelemetryService.stop(getApplication())
        _state.update {
            it.copy(
                connectedMac = null,
                handshakeReady = false,
                measuring = false,
                historySyncing = false,
                statusLine = "Desconectado.",
            )
        }
    }

    fun syncHistory() {
        saveSettings()
        if (!_state.value.handshakeReady) {
            _state.update {
                it.copy(statusLine = "Conecte e aguarde o handshake antes de sincronizar o histórico.")
            }
            return
        }
        if (_state.value.ingestApiKey.isBlank()) {
            _state.update { it.copy(statusLine = "Defina a API key antes do sync OriginData3.") }
            return
        }
        _state.update {
            it.copy(
                busy = true,
                historySyncing = true,
                historySyncLine = "Pausando FC para ler OriginData3…",
                statusLine = "Sync histórico OriginData3…",
            )
        }
        hband.syncOriginHistory()
    }

    fun tryGattFallback() {
        val mac = _state.value.connectedMac ?: return
        hband.stopHeart()
        if (gattHr == null) {
            gattHr = GattHeartRateClient(
                getApplication(),
                onStatus = { msg -> _state.update { it.copy(statusLine = msg) } },
                onBpm = { bpm, addr ->
                    ingestLive(bpm, DeviceIds.fromMac("GATT-$addr"), "ble_hband")
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
            deviceId = DeviceIds.fromMac(s.deviceId.ifBlank { "HBAND-SIM-001" }),
            listener = { bpm, deviceId, source ->
                _state.update { it.copy(lastSimBpm = bpm, heartRateInput = bpm.toInt().toString()) }
                viewModelScope.launch {
                    val current = _state.value
                    val req = TelemetryDispatch.buildRealtime(
                        patientId = current.patientId,
                        deviceId = DeviceIds.fromMac(deviceId),
                        heartRate = bpm,
                        ingestSource = source,
                    ) ?: return@launch
                    when (val r = repository.ingest(req)) {
                        is ApiResult.Success -> _state.update {
                            it.copy(
                                lastIngest = r.data,
                                authError = null,
                                statusLine = "BLE sim ${bpm.toInt()} bpm → ingest ${r.httpCode}",
                            )
                        }
                        is ApiResult.Failure -> {
                            if (r.isRetryable) outbox.enqueue(req)
                            applyFailure(r)
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
        val s = _state.value
        if (s.ingestApiKey.isBlank()) return
        val req = TelemetryDispatch.buildRealtime(
            patientId = s.patientId,
            deviceId = DeviceIds.fromMac(deviceId),
            heartRate = bpm.toDouble(),
            spo2 = s.lastSpo2?.toDouble(),
            ppgSignal = ppgBuffer.snapshot(),
            ingestSource = source,
        ) ?: return
        ppgBuffer.drain()
        lastIngestAt = now
        viewModelScope.launch {
            when (val r = repository.ingest(req)) {
                is ApiResult.Success -> _state.update {
                    it.copy(lastIngest = r.data, authError = null, statusLine = "FC $bpm bpm → ingest ${r.httpCode}")
                }
                is ApiResult.Failure -> {
                    if (r.isRetryable) outbox.enqueue(req)
                    applyFailure(r)
                }
            }
        }
    }

    private suspend fun ingestRequest(req: WearableIngestRequest, pendingStatus: String) {
        _state.update { it.copy(busy = true, statusLine = pendingStatus, authError = null) }
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
                    applyFailure(r)
                }
            }
        }
    }

    private suspend fun flushOriginSamples(samples: List<OriginVitalSample>) {
        val s = _state.value
        val deviceId = DeviceIds.fromMac(s.connectedMac ?: s.deviceId)
        val readings = samples.mapNotNull {
            TelemetryDispatch.fromOriginSample(it, s.patientId, deviceId)
        }
        if (readings.isEmpty()) {
            _state.update {
                it.copy(
                    busy = false,
                    historySyncing = false,
                    historySyncLine = "Lidos ${samples.size} blocos; nenhum com FC 20–250 — nada enviado.",
                    statusLine = "OriginData3: 0 leituras válidas. FC retomada.",
                    outboxPending = outbox.pending().size,
                )
            }
            return
        }
        val chunks = readings.chunked(200)
        var sent = 0
        var failedMsg: String? = null
        for (chunk in chunks) {
            when (val r = repository.batchIngest(s.patientId, chunk)) {
                is ApiResult.Success -> sent += chunk.size
                is ApiResult.Failure -> {
                    if (r.isRetryable) chunk.forEach { outbox.enqueue(it) }
                    failedMsg = failLabel(r)
                    if (r.isUnauthorized) {
                        _state.update { it.copy(authError = AuthUiMessages.forHttp(r.httpCode)) }
                    }
                    break
                }
            }
        }
        _state.update {
            it.copy(
                busy = false,
                historySyncing = false,
                outboxPending = outbox.pending().size,
                historySyncLine = failedMsg
                    ?: "Histórico: $sent/${readings.size} enviados (${samples.size} blocos lidos).",
                statusLine = failedMsg
                    ?: "OriginData3 OK — $sent leituras. FC retomada.",
            )
        }
    }

    override fun onCleared() {
        session.removeListener(this)
        bleSim?.stop()
        hband.stopAllSensors()
        hband.disconnect()
        gattHr?.close()
        Ve30TelemetryService.stop(getApplication())
        super.onCleared()
    }

    private fun applyFailure(r: ApiResult.Failure, prefix: String? = null) {
        val auth = AuthUiMessages.forHttp(r.httpCode)
        val line = buildString {
            if (prefix != null) {
                append(prefix)
                append(" (${r.httpCode}): ")
                append(r.message)
            } else {
                append(failLabel(r))
            }
        }
        _state.update {
            it.copy(
                busy = false,
                historySyncing = false,
                apiOnline = if (prefix == "Falha health") false else it.apiOnline,
                latest = if (prefix == null && it.statusLine.contains("latest", true)) it.latest else it.latest,
                statusLine = auth ?: line,
                authError = auth,
            )
        }
    }

    private fun failLabel(r: ApiResult.Failure): String {
        AuthUiMessages.forHttp(r.httpCode)?.let { return it }
        return buildString {
            append("Erro ${r.httpCode}: ${r.message}")
            if (r.isValidationError) append(" — payload inválido (não reenviar)")
            if (r.isRateLimited) append(" — rate limit; aguarde")
            r.requestId?.let { append(" [req=$it]") }
        }
    }
}

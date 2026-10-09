package com.healthtech.companion.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.healthtech.companion.BuildConfig
import com.healthtech.companion.ble.BlePermissions
import com.healthtech.companion.ble.BleTransport
import com.healthtech.companion.ble.HbandProtocolClient
import com.healthtech.companion.ble.ScannedDevice
import com.healthtech.companion.ble.SimulatedBleTransport
import com.healthtech.companion.ble.StandardWatchClient
import com.healthtech.companion.ble.prefersVeepooProtocol
import com.healthtech.companion.data.AppPrefs
import com.healthtech.companion.data.ConsentNotice
import com.healthtech.companion.net.ApiResult
import com.healthtech.companion.net.BaseUrlPolicy
import com.healthtech.companion.net.HealthtechRepository
import com.healthtech.companion.net.dto.ProcessedTelemetry
import com.healthtech.companion.net.dto.WearableIngestRequest
import com.healthtech.companion.net.outbox.FileOutboxStore
import com.healthtech.companion.net.outbox.OutboxFlusher
import com.healthtech.companion.net.outbox.OutboxItem
import java.io.File
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
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
    val lastBpSys: Int? = null,
    val lastBpDia: Int? = null,
    val lastTempC: Double? = null,
    val linkKind: String = "",
    val measuring: Boolean = false,
    val consentGranted: Boolean = false,
    val consentAt: String = "",
)

class MainViewModel(app: Application) : AndroidViewModel(app) {

    private val prefs = AppPrefs(app)

    private val _state = MutableStateFlow(
        UiState(
            baseUrl = prefs.baseUrl,
            ingestApiKey = prefs.ingestApiKey,
            patientId = prefs.patientId,
            deviceId = prefs.deviceId,
            consentGranted = prefs.consentIsCurrent(),
            consentAt = prefs.consentAt,
        ),
    )
    val state: StateFlow<UiState> = _state.asStateFlow()

    private var repository: HealthtechRepository = buildRepoOrPlaceholder()
    private val outboxStore = FileOutboxStore(File(app.filesDir, "outbox.json"))
    private var outboxItems: MutableList<OutboxItem> = outboxStore.load()
    private var outbox: OutboxFlusher = bindOutbox(repository, outboxItems)
    private var bleSim: BleTransport? = null
    private var activeGen = 0
    private var standardGen = 0
    private var hbandGen = 0
    private val gate = LiveIngestGate()
    private var flushJob: Job? = null
    private val standard = StandardWatchClient(
        app,
        object : StandardWatchClient.Listener {
            override fun onStatus(message: String) {
                if (!standardActive()) return
                _state.update { it.copy(statusLine = message) }
            }

            override fun onReady(mac: String, profiles: List<String>) {
                if (!standardActive()) return
                val deviceId = "WATCH-$mac"
                prefs.deviceId = deviceId
                _state.update {
                    it.copy(
                        handshakeReady = true,
                        connectedMac = mac,
                        deviceId = deviceId,
                        linkKind = "standard",
                        measuring = true,
                        statusLine = "Perfil padrão pronto (${profiles.joinToString()}).",
                    )
                }
            }

            override fun onHeartRate(bpm: Int, mac: String) {
                if (!standardActive()) return
                _state.update {
                    it.copy(lastLiveBpm = bpm, lastSimBpm = bpm.toDouble(), heartRateInput = bpm.toString(), measuring = true)
                }
                noteLive("WATCH-$mac", "ble_standard")
            }

            override fun onSpo2(percent: Int, mac: String) {
                if (!standardActive()) return
                _state.update { it.copy(lastSpo2 = percent, statusLine = "SpO2 $percent%") }
                noteLive("WATCH-$mac", "ble_standard")
            }

            override fun onBloodPressure(systolic: Int, diastolic: Int, mac: String) {
                if (!standardActive()) return
                _state.update {
                    it.copy(lastBpSys = systolic, lastBpDia = diastolic, statusLine = "PA $systolic/$diastolic mmHg")
                }
                noteLive("WATCH-$mac", "ble_standard")
            }

            override fun onTemperature(celsius: Double, mac: String) {
                if (!standardActive()) return
                _state.update { it.copy(lastTempC = celsius, statusLine = "Temp ${"%.1f".format(celsius)} °C") }
                noteLive("WATCH-$mac", "ble_standard")
            }

            override fun onNoHealthProfile(mac: String) {
                if (!standardActive()) return
                _state.update {
                    it.copy(
                        measuring = false,
                        handshakeReady = false,
                        statusLine = "Este aparelho não publica FC, SpO2, pressão nem temperatura. " +
                            "Apple Watch e vários Garmin/Samsung não abrem esses serviços. " +
                            "Se for HBand, toque em Protocolo HBand.",
                    )
                }
            }

            override fun onDisconnected(mac: String) {
                if (!standardActive()) return
                standardGen = 0
                dropLiveSample()
                _state.update { it.disconnected("Perfil padrão desconectado.") }
            }
        },
    )
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
                if (!hbandActive()) return
                _state.update { it.copy(statusLine = message) }
            }

            override fun onReady(mac: String) {
                if (!hbandActive()) return
                _state.update {
                    it.copy(
                        handshakeReady = true,
                        connectedMac = mac,
                        deviceId = "HBAND-$mac",
                        linkKind = "hband",
                        measuring = true,
                        statusLine = "Handshake ok. Medindo FC…",
                    )
                }
                prefs.deviceId = "HBAND-$mac"
            }

            override fun onHeartRate(bpm: Int, mac: String, status: String) {
                if (!hbandActive()) return
                _state.update {
                    it.copy(
                        lastLiveBpm = bpm,
                        lastSimBpm = bpm.toDouble(),
                        heartRateInput = bpm.toString(),
                        measuring = true,
                    )
                }
                noteLive("HBAND-$mac", "ble_hband")
            }

            override fun onSpo2(percent: Int, mac: String) {
                if (!hbandActive()) return
                _state.update { it.copy(lastSpo2 = percent, statusLine = "SpO2 $percent%") }
                noteLive("HBAND-$mac", "ble_hband")
            }

            override fun onDisconnected(mac: String, reason: String?) {
                if (!hbandActive()) return
                if (mac.isNotBlank() && mac != _state.value.connectedMac) return
                hbandGen = 0
                dropLiveSample()
                _state.update {
                    it.disconnected("Desconectado${reason?.let { r -> ": $r" } ?: ""}")
                }
            }

            override fun onError(message: String) {
                if (!hbandActive()) return
                _state.update { it.copy(statusLine = message, measuring = false) }
            }
        },
    )

    init {
        _state.update { it.copy(outboxPending = outbox.pending().size) }
        if (runCatching { BaseUrlPolicy.normalize(prefs.baseUrl, BuildConfig.DEBUG) }.isFailure) {
            _state.update {
                it.copy(statusLine = "A URL salva não é aceita. Use HTTPS ou, no debug, um IP privado.")
            }
        }
    }

    private fun standardActive() = standardGen != 0 && standardGen == activeGen

    private fun hbandActive() = hbandGen != 0 && hbandGen == activeGen

    private fun beginLink(kind: String) {
        activeGen += 1
        dropLiveSample()
        if (kind == "hband") {
            hbandGen = activeGen
            standardGen = 0
        } else {
            standardGen = activeGen
            hbandGen = 0
        }
    }

    private fun buildRepo(): HealthtechRepository {
        val s = _state.value
        return HealthtechRepository.create(
            baseUrl = s.baseUrl.ifBlank { prefs.baseUrl },
            apiKey = s.ingestApiKey,
            enableHttpLogging = BuildConfig.DEBUG,
            allowPrivateCleartext = BuildConfig.DEBUG,
        )
    }

    private fun buildRepoOrPlaceholder(): HealthtechRepository {
        return try {
            buildRepo()
        } catch (e: IllegalArgumentException) {
            HealthtechRepository.create(
                baseUrl = "https://localhost",
                apiKey = "",
                enableHttpLogging = false,
                allowPrivateCleartext = false,
            )
        }
    }

    private fun bindOutbox(
        repo: HealthtechRepository,
        items: MutableList<OutboxItem>,
    ): OutboxFlusher {
        return OutboxFlusher(repo, items).also { flusher ->
            flusher.onChanged = {
                outboxStore.save(items)
                _state.update { it.copy(outboxPending = flusher.pending().size) }
            }
        }
    }

    private fun rebuildClients(): Boolean {
        return try {
            repository = buildRepo()
            outboxItems = outboxStore.load()
            outbox = bindOutbox(repository, outboxItems)
            _state.update { it.copy(outboxPending = outbox.pending().size) }
            true
        } catch (e: IllegalArgumentException) {
            _state.update { it.copy(statusLine = e.message ?: "URL inválida.") }
            false
        }
    }

    fun onBaseUrlChange(v: String) = _state.update { it.copy(baseUrl = v) }
    fun onApiKeyChange(v: String) = _state.update { it.copy(ingestApiKey = v) }
    fun onPatientIdChange(v: String) = _state.update { it.copy(patientId = v) }
    fun onDeviceIdChange(v: String) = _state.update { it.copy(deviceId = v) }
    fun onHeartRateChange(v: String) = _state.update { it.copy(heartRateInput = v) }
    fun toggleShowKey() = _state.update { it.copy(showKey = !it.showKey) }

    fun saveSettings(): Boolean {
        val s = _state.value
        val normalized = try {
            BaseUrlPolicy.normalize(s.baseUrl, allowPrivateCleartext = BuildConfig.DEBUG)
        } catch (e: IllegalArgumentException) {
            _state.update { it.copy(statusLine = e.message ?: "URL inválida.") }
            return false
        }
        prefs.baseUrl = normalized
        prefs.ingestApiKey = s.ingestApiKey
        prefs.patientId = s.patientId
        prefs.deviceId = s.deviceId
        _state.update { it.copy(baseUrl = prefs.baseUrl) }
        return rebuildClients()
    }

    fun checkHealth() {
        if (!saveSettings()) return
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

    fun acceptConsent() {
        val stamp = java.time.Instant.now().toString()
        prefs.consentGranted = true
        prefs.consentAt = stamp
        prefs.consentVersion = ConsentNotice.VERSION
        if (!prefs.consentIsCurrent()) {
            _state.update { it.copy(statusLine = "Não foi possível gravar o consentimento no cofre do aparelho.") }
            return
        }
        _state.update {
            it.copy(
                consentGranted = true,
                consentAt = stamp,
                statusLine = "Consentimento registrado. O envio de telemetria está liberado.",
            )
        }
    }

    fun revokeConsent() {
        prefs.consentGranted = false
        prefs.consentAt = ""
        prefs.consentVersion = ""
        bleSim?.stop()
        bleSim = null
        outbox.clear()
        disconnectDevice()
        _state.update {
            it.copy(
                consentGranted = false,
                consentAt = "",
                bleSimRunning = false,
                outboxPending = 0,
                statusLine = "Consentimento revogado. A coleta parou e a outbox local foi apagada.",
            )
        }
    }

    fun sendHeartRate() {
        if (!consentAllowsSend()) return
        if (!saveSettings()) return
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
        if (!consentAllowsSend()) return
        if (!saveSettings()) return
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
        if (!saveSettings()) return
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
        if (!saveSettings()) return
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
        if (!saveSettings()) return
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
        if (!saveSettings()) return
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
        if (!saveSettings()) return
        val kind = if (prefersVeepooProtocol(device.name)) "hband" else "standard"
        beginLink(kind)
        hband.stopScan()
        hband.disconnect()
        standard.close()
        _state.update { it.opening(device.mac, kind, "Conectando ${device.label}…") }
        if (kind == "hband") {
            hband.connect(device.mac, device.name.takeIf { it != "N/A" })
        } else {
            standard.connect(device.mac)
        }
    }

    fun connectAlternateProtocol() {
        val mac = _state.value.connectedMac ?: return
        val name = _state.value.scannedDevices.firstOrNull { it.mac == mac }?.name
        if (_state.value.linkKind == "standard") {
            beginLink("hband")
            standard.close()
            _state.update { it.opening(mac, "hband", "Tentando protocolo HBand em $mac…") }
            hband.connect(mac, name?.takeIf { it != "N/A" })
        } else {
            beginLink("standard")
            hband.disconnect()
            _state.update { it.opening(mac, "standard", "Tentando perfil Bluetooth padrão em $mac…") }
            standard.connect(mac)
        }
    }

    fun disconnectDevice() {
        activeGen += 1
        standardGen = 0
        hbandGen = 0
        dropLiveSample()
        hband.disconnect()
        standard.close()
        _state.update { it.disconnected("Desconectado.") }
    }

    fun toggleBleSimulator() {
        if (!consentAllowsSend()) return
        if (!saveSettings()) return
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

    private fun noteLive(deviceId: String, source: String) {
        if (!consentAllowsSend(quiet = true)) return
        val s = _state.value
        val bpm = s.lastLiveBpm ?: return
        if (s.ingestApiKey.isBlank()) {
            if (!s.statusLine.startsWith("Defina a API key")) {
                _state.update { it.copy(statusLine = "Defina a API key para enviar a medição.") }
            }
            return
        }
        val generation = activeGen
        val pairedBp = s.lastBpSys != null && s.lastBpDia != null
        val snap = LiveIngestGate.Snapshot(
            generation = generation,
            bpm = bpm,
            deviceId = deviceId,
            source = source,
            spo2 = s.lastSpo2,
            bpSys = if (pairedBp) s.lastBpSys else null,
            bpDia = if (pairedBp) s.lastBpDia else null,
            tempC = s.lastTempC,
        )
        val now = System.currentTimeMillis()
        val due = gate.offer(snap, now)
        if (due != null) {
            launchIngest(due)
        } else {
            scheduleFlush()
        }
    }

    private fun scheduleFlush() {
        if (flushJob?.isActive == true) return
        flushJob = viewModelScope.launch {
            val wait = gate.millisUntilDue(System.currentTimeMillis()).coerceAtLeast(1L)
            delay(wait)
            val snap = gate.pollDue(System.currentTimeMillis()) ?: return@launch
            launchIngest(snap)
        }
    }

    private fun launchIngest(snap: LiveIngestGate.Snapshot) {
        if (!consentAllowsSend(quiet = true)) return
        if (snap.generation != activeGen) return
        val patientId = _state.value.patientId
        viewModelScope.launch {
            if (snap.generation != activeGen) return@launch
            val req = WearableIngestRequest(
                patientId = patientId,
                deviceId = snap.deviceId,
                heartRate = snap.bpm.toDouble(),
                spo2 = snap.spo2?.toDouble(),
                bloodPressureSys = snap.bpSys?.toDouble(),
                bloodPressureDia = snap.bpDia?.toDouble(),
                bodyTempC = snap.tempC,
                filterType = "BMO",
                ingestSource = snap.source,
            )
            when (val r = repository.ingest(req)) {
                is ApiResult.Success -> _state.update {
                    it.copy(lastIngest = r.data, statusLine = "FC ${snap.bpm} bpm → ingest ${r.httpCode}")
                }
                is ApiResult.Failure -> {
                    if (r.isRetryable) outbox.enqueue(req)
                    _state.update { it.copy(statusLine = failLabel(r)) }
                }
            }
        }
    }

    private fun consentAllowsSend(quiet: Boolean = false): Boolean {
        if (prefs.consentIsCurrent()) return true
        if (!quiet) {
            _state.update { it.copy(statusLine = "O envio espera o consentimento específico do titular.") }
        }
        return false
    }

    private fun dropLiveSample() {
        flushJob?.cancel()
        flushJob = null
        gate.clear()
    }

    private fun UiState.disconnected(status: String) = copy(
        connectedMac = null,
        handshakeReady = false,
        measuring = false,
        linkKind = "",
        lastLiveBpm = null,
        lastSpo2 = null,
        lastBpSys = null,
        lastBpDia = null,
        lastTempC = null,
        statusLine = status,
    )

    private fun UiState.opening(mac: String, kind: String, status: String) = copy(
        scanning = false,
        connectedMac = mac,
        handshakeReady = false,
        measuring = false,
        linkKind = kind,
        lastLiveBpm = null,
        lastSpo2 = null,
        lastBpSys = null,
        lastBpDia = null,
        lastTempC = null,
        statusLine = status,
    )

    override fun onCleared() {
        dropLiveSample()
        bleSim?.stop()
        hband.disconnect()
        standard.close()
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

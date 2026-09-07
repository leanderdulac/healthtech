package com.healthtech.companion.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Cloud
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.healthtech.companion.ble.ScannedDevice
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(viewModel: MainViewModel) {
    val state by viewModel.state.collectAsState()
    val scroll = rememberScrollState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            "Saúde Responsiva",
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            "Companion MVP",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.secondary,
                        )
                    }
                },
                actions = {
                    val online = state.apiOnline
                    Icon(
                        imageVector = if (online == true) Icons.Default.Cloud else Icons.Default.CloudOff,
                        contentDescription = null,
                        tint = when (online) {
                            true -> MaterialTheme.colorScheme.tertiary
                            false -> MaterialTheme.colorScheme.error
                            null -> MaterialTheme.colorScheme.onSurfaceVariant
                        },
                        modifier = Modifier.padding(end = 16.dp),
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp)
                .verticalScroll(scroll),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            StatusCard(state)

            ConfigCard(state, viewModel)

            BleCard(state, viewModel)

            ActionsCard(state, viewModel)

            TelemetryCard(state)

            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun StatusCard(state: UiState) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "Status",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.primary,
                    fontWeight = FontWeight.SemiBold,
                )
                if (state.busy) {
                    Spacer(Modifier.width(12.dp))
                    CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        strokeWidth = 2.dp,
                    )
                }
            }
            Text(
                state.statusLine,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            if (state.outboxPending > 0) {
                Text(
                    "Outbox pendente: ${state.outboxPending}",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.secondary,
                )
            }
        }
    }
}

@Composable
private fun ConfigCard(state: UiState, viewModel: MainViewModel) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                "Conexão API",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
                fontWeight = FontWeight.SemiBold,
            )
            OutlinedTextField(
                value = state.baseUrl,
                onValueChange = viewModel::onBaseUrlChange,
                label = { Text("Base URL") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = state.ingestApiKey,
                onValueChange = viewModel::onApiKeyChange,
                label = { Text("API Key (wearables:write)") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                visualTransformation = if (state.showKey) {
                    VisualTransformation.None
                } else {
                    PasswordVisualTransformation()
                },
                trailingIcon = {
                    IconButton(onClick = viewModel::toggleShowKey) {
                        Icon(
                            if (state.showKey) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                            contentDescription = "Mostrar/ocultar key",
                        )
                    }
                },
            )
            OutlinedTextField(
                value = state.patientId,
                onValueChange = viewModel::onPatientIdChange,
                label = { Text("patient_id") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = state.deviceId,
                onValueChange = viewModel::onDeviceIdChange,
                label = { Text("device_id") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = viewModel::saveSettings,
                    enabled = !state.busy,
                    modifier = Modifier.weight(1f),
                ) {
                    Text("Salvar")
                }
                Button(
                    onClick = viewModel::checkHealth,
                    enabled = !state.busy,
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("Testar")
                }
            }
        }
    }
}

@Composable
private fun BleCard(state: UiState, viewModel: MainViewModel) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                "Pulseira BLE",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                when {
                    state.lastLiveBpm != null ->
                        "FC ao vivo ${state.lastLiveBpm} bpm" +
                            (state.lastSpo2?.let { " · SpO2 $it%" } ?: "")
                    state.handshakeReady -> "Handshake ok. Medindo…"
                    state.connectedMac != null -> "Conectado ${state.connectedMac}. Handshake em curso."
                    else ->
                        "O scan vê todos os BLE. Conecte na pulseira (nome no topo). " +
                            "Fone/TV não enviam FC. A leitura só vale após senha 0000 + perfil."
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = { if (state.scanning) viewModel.stopScan() else viewModel.startScan() },
                    enabled = !state.busy,
                    modifier = Modifier.weight(1f),
                ) {
                    Text(if (state.scanning) "Parar scan" else "Escanear")
                }
                OutlinedButton(
                    onClick = viewModel::disconnectDevice,
                    enabled = state.connectedMac != null,
                    modifier = Modifier.weight(1f),
                ) {
                    Text("Desconectar")
                }
            }
            if (state.scannedDevices.isNotEmpty()) {
                Text(
                    "Toque na pulseira (não no primeiro BLE qualquer):",
                    style = MaterialTheme.typography.labelMedium,
                )
                state.scannedDevices.take(12).forEach { dev ->
                    DeviceRow(dev, selected = dev.mac == state.connectedMac) {
                        viewModel.connectDevice(dev)
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = viewModel::tryGattFallback,
                    enabled = state.connectedMac != null && !state.busy,
                    modifier = Modifier.weight(1f),
                ) {
                    Text("GATT SIG")
                }
                OutlinedButton(
                    onClick = viewModel::toggleBleSimulator,
                    enabled = !state.busy,
                    modifier = Modifier.weight(1f),
                ) {
                    Text(if (state.bleSimRunning) "Parar sim" else "Simular")
                }
            }
        }
    }
}

@Composable
private fun DeviceRow(device: ScannedDevice, selected: Boolean, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 6.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                device.label + if (device.wearableLikely) "  · pulseira?" else "",
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = if (selected || device.wearableLikely) FontWeight.SemiBold else FontWeight.Normal,
                color = if (device.wearableLikely) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurface
                },
            )
            Text(
                device.mac,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Text("${device.rssi} dBm", style = MaterialTheme.typography.labelSmall)
    }
}

@Composable
private fun ActionsCard(state: UiState, viewModel: MainViewModel) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                "Telemetria",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
                fontWeight = FontWeight.SemiBold,
            )
            OutlinedTextField(
                value = state.heartRateInput,
                onValueChange = viewModel::onHeartRateChange,
                label = { Text("Frequência cardíaca (BPM)") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                leadingIcon = {
                    Icon(Icons.Default.Favorite, contentDescription = null, tint = MaterialTheme.colorScheme.error)
                },
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = viewModel::sendHeartRate,
                enabled = !state.busy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.AutoMirrored.Filled.Send, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Text("Enviar ingest (POST)")
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = viewModel::smokeHeart,
                    enabled = !state.busy,
                    modifier = Modifier.weight(1f),
                ) { Text("Smoke 78") }
                OutlinedButton(
                    onClick = viewModel::enqueueAndFlush,
                    enabled = !state.busy,
                    modifier = Modifier.weight(1f),
                ) { Text("Outbox flush") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = viewModel::loadLatest,
                    enabled = !state.busy,
                    modifier = Modifier.weight(1f),
                ) { Text("Latest") }
                OutlinedButton(
                    onClick = viewModel::loadHistory,
                    enabled = !state.busy,
                    modifier = Modifier.weight(1f),
                ) { Text("History") }
            }
        }
    }
}

@Composable
private fun TelemetryCard(state: UiState) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                "Última resposta",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
                fontWeight = FontWeight.SemiBold,
            )
            val ingest = state.lastIngest
            if (ingest != null) {
                MonoLine("ingest patient: ${ingest.patientId ?: "—"}")
                MonoLine("timestamp: ${ingest.timestamp ?: "—"}")
                ClinicalAlertBlock(ingest.clinicalAlerts)
                MonoLine("anomaly: ${ingest.anomalyDetection?.get("modo") ?: ingest.anomalyDetection ?: "—"}")
            } else {
                Text("Nenhum ingest ainda.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }

            Spacer(Modifier.height(8.dp))
            Text(
                "Latest no servidor",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.secondary,
            )
            val latest = state.latest
            if (latest != null) {
                MonoLine("patient: ${latest.patientId ?: "—"}")
                MonoLine("ts: ${latest.timestamp ?: "—"}")
                ClinicalAlertBlock(latest.clinicalAlerts)
            } else {
                Text("Toque em Latest.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }

            if (state.historyPreview.isNotBlank()) {
                Spacer(Modifier.height(8.dp))
                Text(
                    "History",
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.secondary,
                )
                Text(
                    state.historyPreview,
                    fontFamily = FontFamily.Monospace,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun ClinicalAlertBlock(alerts: Map<String, Any?>?) {
    if (alerts.isNullOrEmpty()) {
        MonoLine("alerta: —")
        return
    }
    val isTrue = alerts["is_true_alert"] == true
    val severity = alerts["severity"]?.toString() ?: "none"
    val name = alerts["primary_alert_name"]?.toString()
    val ruleId = alerts["primary_rule_id"]?.toString()
    @Suppress("UNCHECKED_CAST")
    val care = alerts["care_line"] as? Map<String, Any?>
    val stars = care?.get("priority_label")?.toString()
        ?: when (severity) {
            "leve" -> "★"
            "moderado" -> "★★"
            "critico" -> "★★★"
            else -> ""
        }
    if (!isTrue || severity == "none") {
        MonoLine("alerta: nenhum (decision=${alerts["decision"] ?: "—"})")
        return
    }
    Text(
        "$stars  ${severity.uppercase()}  ${name ?: ruleId ?: "alerta clínico"}",
        style = MaterialTheme.typography.bodyMedium,
        fontWeight = FontWeight.SemiBold,
        color = when (severity) {
            "critico" -> MaterialTheme.colorScheme.error
            "moderado" -> MaterialTheme.colorScheme.secondary
            else -> MaterialTheme.colorScheme.tertiary
        },
    )
    if (!ruleId.isNullOrBlank()) {
        MonoLine("regra: $ruleId")
    }
    val nurse = care?.get("nurse")?.toString()
    val acs = care?.get("acs")?.toString()
    val deadline = care?.get("acs_deadline_label")?.toString()
    if (!nurse.isNullOrBlank()) {
        Text("Enfermeira: $nurse", style = MaterialTheme.typography.bodySmall)
    }
    if (!acs.isNullOrBlank()) {
        Text(
            "ACS (${deadline ?: "—"}): $acs",
            style = MaterialTheme.typography.bodySmall,
        )
    }
    Text(
        "Apoio à decisão — não é diagnóstico nem protocolo institucional.",
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@Composable
private fun MonoLine(text: String) {
    Text(
        text,
        fontFamily = FontFamily.Monospace,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

package com.healthtech.companion.ui

/**
 * Notas de UI para a Activity principal do Sprint A (não é Activity real —
 * copie para MainActivity / Compose).
 *
 * Layout mínimo:
 *  - RecyclerView/lista de devices (scan)
 *  - Botão Conectar / Desconectar
 *  - TextView BPM
 *  - TextView último HTTP code + snippet
 *  - Botão "Smoke API" (sem BLE) → HealthtechApiClient.smokeHeart
 *
 * Permissões runtime (API 31+):
 *  BLUETOOTH_SCAN, BLUETOOTH_CONNECT
 *  (location se target ≤ 30)
 *
 * Pseudo-fluxo:
 * ```
 * manager = HbandConnectionManager(this)
 * api = HealthtechApiClient(BuildConfig.HEALTHTECH_BASE_URL, BuildConfig.HEALTHTECH_INGEST_API_KEY)
 * collector = HbandRealtimeCollector(manager, api, BuildConfig.HEALTHTECH_PATIENT_ID)
 * manager.initSdk()
 * manager.setListener(...)
 * collector.setUiCallback(...)
 * scanBtn → manager.startScan()
 * connect → manager.connect(mac) → onReady → collector.startHeart()
 * ```
 */
object SprintAActivityNotes

package com.healthtech.companion.data

import android.content.Context
import com.healthtech.companion.BuildConfig
import com.healthtech.companion.net.HealthtechRetrofitFactory

/**
 * Preferências do companion. API key em SharedPreferences privadas
 * (produção: EncryptedSharedPreferences / Keystore).
 *
 * Não sobrescreve URL salva pelo usuário e não injeta chave de teste.
 */
class AppPrefs(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    var baseUrl: String
        get() = prefs.getString(KEY_BASE_URL, null)
            ?.takeIf { it.isNotBlank() }
            ?: BuildConfig.DEFAULT_BASE_URL.ifBlank {
                HealthtechRetrofitFactory.DEFAULT_LOCAL_BASE
            }
        set(value) = prefs.edit().putString(KEY_BASE_URL, value.trim().trimEnd('/')).apply()

    var ingestApiKey: String
        get() = prefs.getString(KEY_INGEST_KEY, null)
            ?.takeIf { it.isNotBlank() }
            ?: BuildConfig.DEFAULT_INGEST_API_KEY
        set(value) = prefs.edit().putString(KEY_INGEST_KEY, value.trim()).apply()

    var patientId: String
        get() = prefs.getString(KEY_PATIENT_ID, null)
            ?.takeIf { it.isNotBlank() }
            ?: BuildConfig.DEFAULT_PATIENT_ID.ifBlank { "PAT-HBAND-001" }
        set(value) = prefs.edit().putString(KEY_PATIENT_ID, value.trim()).apply()

    var deviceId: String
        get() = prefs.getString(KEY_DEVICE_ID, null)
            ?.takeIf { it.isNotBlank() }
            ?: "HBAND-MVP-001"
        set(value) = prefs.edit().putString(KEY_DEVICE_ID, value.trim()).apply()

    companion object {
        private const val PREFS_NAME = "healthtech_companion"
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_INGEST_KEY = "ingest_api_key"
        private const val KEY_PATIENT_ID = "patient_id"
        private const val KEY_DEVICE_ID = "device_id"
    }
}

package com.healthtech.companion.data

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.healthtech.companion.BuildConfig
import com.healthtech.companion.net.HealthtechRetrofitFactory

/**
 * URL, paciente e device ficam no mesmo cofre da API key.
 * A chave nunca volta de BuildConfig nem de SharedPreferences em claro.
 */
class AppPrefs(context: Context) {
    private val appContext = context.applicationContext
    private val legacy = appContext.getSharedPreferences(LEGACY_PREFS, Context.MODE_PRIVATE)
    private val secure = openSecure()

    init {
        migrateFromLegacy()
    }

    var baseUrl: String
        get() = read(KEY_BASE_URL)
            ?: BuildConfig.DEFAULT_BASE_URL.ifBlank {
                HealthtechRetrofitFactory.DEFAULT_LOCAL_BASE
            }
        set(value) = write(KEY_BASE_URL, value.trim().trimEnd('/'))

    var ingestApiKey: String
        get() = secure?.getString(KEY_INGEST_KEY, null)?.trim().orEmpty()
        set(value) {
            val dest = secure ?: return
            dest.edit().putString(KEY_INGEST_KEY, value.trim()).apply()
        }

    var patientId: String
        get() = read(KEY_PATIENT_ID)
            ?: BuildConfig.DEFAULT_PATIENT_ID.ifBlank { "PAT-HBAND-001" }
        set(value) = write(KEY_PATIENT_ID, value.trim())

    var deviceId: String
        get() = read(KEY_DEVICE_ID) ?: "HBAND-MVP-001"
        set(value) = write(KEY_DEVICE_ID, value.trim())

    var consentGranted: Boolean
        get() = secure?.getBoolean(KEY_CONSENT, false) ?: false
        set(value) {
            val dest = secure ?: return
            dest.edit().putBoolean(KEY_CONSENT, value).apply()
        }

    var consentAt: String
        get() = secure?.getString(KEY_CONSENT_AT, null).orEmpty()
        set(value) {
            val dest = secure ?: return
            dest.edit().putString(KEY_CONSENT_AT, value).apply()
        }

    var consentVersion: String
        get() = secure?.getString(KEY_CONSENT_VERSION, null).orEmpty()
        set(value) {
            val dest = secure ?: return
            dest.edit().putString(KEY_CONSENT_VERSION, value).apply()
        }

    fun consentIsCurrent(): Boolean =
        consentGranted && consentVersion == ConsentNotice.VERSION

    private fun read(key: String): String? {
        val fromSecure = secure?.getString(key, null)?.takeIf { it.isNotBlank() }
        if (fromSecure != null) return fromSecure
        if (key == KEY_INGEST_KEY) return null
        return legacy.getString(key, null)?.takeIf { it.isNotBlank() }
    }

    private fun write(key: String, value: String) {
        val dest = secure
        if (dest != null) {
            dest.edit().putString(key, value).apply()
            legacy.edit().remove(key).apply()
        } else if (key != KEY_INGEST_KEY) {
            legacy.edit().putString(key, value).apply()
        }
    }

    private fun openSecure(): SharedPreferences? = try {
        val master = MasterKey.Builder(appContext)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            appContext,
            SECURE_PREFS,
            master,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    } catch (e: Exception) {
        Log.e(TAG, "Cofre da API key indisponível")
        null
    }

    private fun migrateFromLegacy() {
        val dest = secure ?: return
        val editor = dest.edit()
        var moved = false
        for (key in LEGACY_KEYS) {
            val current = dest.getString(key, null)
            val old = legacy.getString(key, null)
            if (current.isNullOrBlank() && !old.isNullOrBlank()) {
                editor.putString(key, old)
                moved = true
            }
        }
        if (moved) editor.apply()
        legacy.edit().clear().apply()
    }

    companion object {
        private const val TAG = "AppPrefs"
        private const val LEGACY_PREFS = "healthtech_companion"
        private const val SECURE_PREFS = "healthtech_companion_secure"
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_INGEST_KEY = "ingest_api_key"
        private const val KEY_PATIENT_ID = "patient_id"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_CONSENT = "consent_granted"
        private const val KEY_CONSENT_AT = "consent_at"
        private const val KEY_CONSENT_VERSION = "consent_version"
        private val LEGACY_KEYS = listOf(KEY_BASE_URL, KEY_INGEST_KEY, KEY_PATIENT_ID, KEY_DEVICE_ID)
    }
}

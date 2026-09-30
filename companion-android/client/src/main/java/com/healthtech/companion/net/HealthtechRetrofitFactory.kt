package com.healthtech.companion.net

import android.util.Log
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Configuração padrão OkHttp + Retrofit para a Secure API.
 *
 * Base URL e API key vêm da UI. A chave não entra no APK.
 */
object HealthtechRetrofitFactory {

    /** Emulador Android → processo no host (uvicorn --port 8080). */
    const val DEFAULT_LOCAL_BASE = "http://10.0.2.2:8080"

    /** Placeholder de documentação. Não usar como default de build. */
    const val PRODUCTION_SECURE_BASE_EXAMPLE =
        "https://YOUR_SECURE_API.run.app"

    fun gson(): Gson = GsonBuilder()
        .serializeNulls()
        .create()

    fun okHttp(
        apiKey: String,
        enableHttpLogging: Boolean = false,
        connectTimeoutSec: Long = 20,
        readTimeoutSec: Long = 30,
    ): OkHttpClient {
        val builder = OkHttpClient.Builder()
            .connectTimeout(connectTimeoutSec, TimeUnit.SECONDS)
            .readTimeout(readTimeoutSec, TimeUnit.SECONDS)
            .writeTimeout(readTimeoutSec, TimeUnit.SECONDS)
            .addInterceptor(apiKeyInterceptor(apiKey))
            .addInterceptor(userAgentInterceptor())

        if (enableHttpLogging) {
            builder.addInterceptor(safeLogInterceptor())
        }
        return builder.build()
    }

    fun retrofit(
        baseUrl: String,
        apiKey: String,
        enableHttpLogging: Boolean = false,
        allowPrivateCleartext: Boolean = false,
    ): Retrofit {
        val normalized = BaseUrlPolicy.normalize(baseUrl, allowPrivateCleartext)
        val root = if (normalized.endsWith("/")) normalized else "$normalized/"
        return Retrofit.Builder()
            .baseUrl(root)
            .client(okHttp(apiKey, enableHttpLogging))
            .addConverterFactory(GsonConverterFactory.create(gson()))
            .build()
    }

    fun createApi(
        baseUrl: String = DEFAULT_LOCAL_BASE,
        apiKey: String,
        enableHttpLogging: Boolean = false,
        allowPrivateCleartext: Boolean = false,
    ): HealthtechApi = retrofit(
        baseUrl,
        apiKey,
        enableHttpLogging,
        allowPrivateCleartext,
    ).create(HealthtechApi::class.java)

    private fun apiKeyInterceptor(apiKey: String): Interceptor = Interceptor { chain ->
        val original = chain.request()
        val path = original.url.encodedPath
        val req = original.newBuilder()
            .header("Accept", "application/json")
            .apply {
                if (original.body != null) {
                    header("Content-Type", "application/json")
                }
                if (apiKey.isNotBlank() && !path.endsWith("/api/health")) {
                    header("X-API-Key", apiKey)
                }
            }
            .build()
        chain.proceed(req)
    }

    /** Método e status apenas. Corpo e cabeçalho da chave não vão para o logcat. */
    private fun safeLogInterceptor(): Interceptor = Interceptor { chain ->
        val response = chain.proceed(chain.request())
        Log.i(HTTP_LOG_TAG, "${chain.request().method} -> ${response.code}")
        response
    }

    private fun userAgentInterceptor(): Interceptor = Interceptor { chain ->
        val req = chain.request().newBuilder()
            .header("User-Agent", "HealthtechCompanion/1.1 (Android)")
            .build()
        chain.proceed(req)
    }

    private const val HTTP_LOG_TAG = "HealthtechHttp"
}

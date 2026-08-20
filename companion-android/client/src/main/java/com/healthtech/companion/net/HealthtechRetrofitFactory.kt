package com.healthtech.companion.net

import com.google.gson.Gson
import com.google.gson.GsonBuilder
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Configuração padrão OkHttp + Retrofit para a Secure API.
 *
 * Base URL e API key vêm da UI / local.properties — nunca de constantes de produção.
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
            val log = HttpLoggingInterceptor().apply {
                level = HttpLoggingInterceptor.Level.BODY
            }
            builder.addInterceptor(log)
        }
        return builder.build()
    }

    fun retrofit(
        baseUrl: String,
        apiKey: String,
        enableHttpLogging: Boolean = false,
    ): Retrofit {
        val root = if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/"
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
    ): HealthtechApi = retrofit(baseUrl, apiKey, enableHttpLogging).create(HealthtechApi::class.java)

    private fun apiKeyInterceptor(apiKey: String): Interceptor = Interceptor { chain ->
        val original = chain.request()
        val path = original.url.encodedPath
        // /api/health é público — mas enviar a key não quebra
        val req = original.newBuilder()
            .header("Accept", "application/json")
            .header("Content-Type", "application/json")
            .apply {
                if (apiKey.isNotBlank() && !path.endsWith("/api/health")) {
                    header("X-API-Key", apiKey)
                } else if (apiKey.isNotBlank()) {
                    // health também pode carregar key sem problema
                    header("X-API-Key", apiKey)
                }
            }
            .build()
        chain.proceed(req)
    }

    private fun userAgentInterceptor(): Interceptor = Interceptor { chain ->
        val req = chain.request().newBuilder()
            .header("User-Agent", "HealthtechCompanion/1.0 (Android)")
            .build()
        chain.proceed(req)
    }
}

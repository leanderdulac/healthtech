package com.healthtech.companion.net

/**
 * Resultado tipado das chamadas HTTP — facilita UI e outbox.
 */
sealed class ApiResult<out T> {
    data class Success<T>(
        val data: T,
        val httpCode: Int = 200,
        val requestId: String? = null,
    ) : ApiResult<T>()

    data class Failure(
        val httpCode: Int,
        val message: String,
        val errorCode: String? = null,
        val requestId: String? = null,
        val body: String? = null,
        val throwable: Throwable? = null,
    ) : ApiResult<Nothing>() {
        val isUnauthorized: Boolean get() = httpCode == 401 || httpCode == 403
        val isValidationError: Boolean get() = httpCode == 422
        val isRateLimited: Boolean get() = httpCode == 429
        val isRetryable: Boolean
            get() = httpCode == 0 || httpCode == 408 || httpCode == 429 || httpCode in 500..599
        val isDeadLetter: Boolean get() = httpCode == 422
    }

    val isSuccess: Boolean get() = this is Success
}

inline fun <T> ApiResult<T>.onSuccess(block: (T) -> Unit): ApiResult<T> {
    if (this is ApiResult.Success) block(data)
    return this
}

inline fun <T> ApiResult<T>.onFailure(block: (ApiResult.Failure) -> Unit): ApiResult<T> {
    if (this is ApiResult.Failure) block(this)
    return this
}

package com.healthtech.companion.telemetry

/**
 * Mensagens de auth para a UI (Sprint A: 401/403 visíveis, sem logar a key).
 */
object AuthUiMessages {
    const val HTTP_401 =
        "Não autorizado (401): API key inválida ou ausente. " +
            "Atualize a chave com escopo wearables:write."

    const val HTTP_403 =
        "Acesso negado (403): a chave não tem o escopo wearables:write."

    fun forHttp(code: Int): String? = when (code) {
        401 -> HTTP_401
        403 -> HTTP_403
        else -> null
    }
}

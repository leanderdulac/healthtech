package com.healthtech.companion.net

import java.net.URI

/**
 * HTTP claro só para a máquina local, o emulador ou um IP privado.
 * Release recusa qualquer URL que não seja HTTPS.
 */
object BaseUrlPolicy {

    fun normalize(raw: String, allowPrivateCleartext: Boolean): String {
        val trimmed = raw.trim().trimEnd('/')
        if (trimmed.isBlank()) {
            throw IllegalArgumentException("Informe a URL da API.")
        }
        val uri = try {
            URI(trimmed)
        } catch (e: Exception) {
            throw IllegalArgumentException("URL da API inválida.")
        }
        if (uri.userInfo != null) {
            throw IllegalArgumentException("A URL não pode trazer usuário ou senha.")
        }
        val host = uri.host?.trim().orEmpty()
        if (host.isEmpty()) {
            throw IllegalArgumentException("A URL da API está sem host.")
        }
        when (uri.scheme?.lowercase()) {
            "https" -> Unit
            "http" -> {
                if (!allowPrivateCleartext || !isLocalOrPrivate(host)) {
                    throw IllegalArgumentException(
                        "HTTP só vale para localhost, o emulador ou um IP privado. Fora isso, use HTTPS.",
                    )
                }
            }
            else -> throw IllegalArgumentException("A URL da API precisa ser http ou https.")
        }
        return trimmed
    }

    fun isLocalOrPrivate(host: String): Boolean {
        val name = host.trim().lowercase().removePrefix("[").removeSuffix("]")
        if (name == "localhost" || name == "10.0.2.2" || name == "::1") return true
        return isPrivateIpv4(name)
    }

    private fun isPrivateIpv4(host: String): Boolean {
        val parts = host.split('.')
        if (parts.size != 4) return false
        val numbers = parts.map { it.toIntOrNull() ?: return false }
        if (numbers.any { it !in 0..255 }) return false
        val a = numbers[0]
        val b = numbers[1]
        return a == 10 ||
            a == 127 ||
            (a == 192 && b == 168) ||
            (a == 172 && b in 16..31) ||
            (a == 169 && b == 254)
    }
}

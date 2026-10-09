package com.healthtech.companion.data

/**
 * Texto mostrado antes de qualquer envio de telemetria.
 * A hipótese que o app exige é o consentimento específico do titular.
 */
object ConsentNotice {
    const val VERSION = "2026-09-28"

    const val TITLE = "Consentimento para dados de saúde"

    val BODY = """
        O Saúde Responsiva trata frequência cardíaca, SpO2, pressão, temperatura e o identificador deste paciente para o piloto de monitoramento.

        A finalidade é o apoio à decisão. O alerta não impõe conduta obrigatória. Você pode pedir a revisão de uma decisão automatizada.

        O envio segue para a API do projeto e para a nuvem que hospeda essa API. Não há outra destinação neste app.

        Este consentimento é específico. Sem ele, o app não envia telemetria. Revogar interrompe a coleta e apaga a outbox local. A eliminação no servidor continua no endpoint administrativo de exclusão.
    """.trimIndent()
}

# Plano de resposta a incidente e comunicação de incidente

Procedimento do produto Saúde Responsiva para incidente de segurança que envolva dado pessoal. Cobre o art. 48 da Lei 13.709/2018 e a Resolução CD/ANPD nº 15/2024. Não substitui o protocolo feito pela pessoa que representa o controlador, e este repositório ainda não nomeia essa pessoa.

## Quando comunicar

Comunicar à ANPD e ao titular quando o incidente puder acarretar risco ou dano relevante. Dado de saúde (frequência cardíaca, SpO2, pressão, temperatura, identificador do paciente) é dado pessoal sensível. Vazamento, acesso não autorizado ou perda desse conjunto entra na avaliação como risco relevante, salvo registro fundamentado do contrário.

Também entra: chave de API exposta, falha da trava por paciente e publicação acidental de telemetria.

## Prazos

Contados do conhecimento de que o incidente afetou dado pessoal. Dias úteis excluem sábado, domingo e feriado nacional.

- Comunicação à ANPD: 3 dias úteis, pelo formulário eletrônico da ANPD. Se faltar dado, a comunicação preliminar sai no prazo e o complemento vem em até 20 dias úteis.
- Comunicação ao titular: o mesmo prazo de 3 dias úteis. Se a comunicação individual for inviável, usar o canal público do produto por no mínimo 3 meses.
- Declaração, no processo da ANPD, de que o titular foi comunicado: até 3 dias úteis depois do fim do prazo de comunicação à ANPD.
- Agente de pequeno porte: os prazos de comunicação contam em dobro, salvo comprometimento da integridade física ou moral do titular.
- Registro do incidente, comunicado ou não: guardar por 5 anos a partir do registro.

## Papéis

- Quem opera a API secure contém o incidente: revogar a chave afetada, bloquear o acesso e preservar log sem copiar telemetria para chat, issue ou e-mail.
- Quem avalia o risco ou dano relevante registra a hora do conhecimento, os titulares atingidos na medida do possível, e a decisão de comunicar ou de não comunicar.
- Quem protocola na ANPD é o controlador, pelo encarregado quando houver nomeação. O nome e o canal do encarregado não estão neste repositório. Sem essa nomeação o protocolo não tem signatário.

## Passos

1. Conter. Tirar a chave do uso, encerrar sessão exposta e impedir novo ingest com a credencial vazada.
2. Preservar. Guardar request id, hora e escopo. Não colar identificador de paciente nem amostra vital no registro do incidente.
3. Avaliar. Dizer se houve acesso, vazamento ou perda de dado pessoal e se o risco ou dano é relevante.
4. Comunicar, se couber, à ANPD e ao titular, no prazo acima. A comunicação preliminar incompleta é preferível a esperar o dossiê fechado.
5. Complementar em até 20 dias úteis e juntar a declaração de comunicação aos titulares.
6. Registrar o incidente por 5 anos, inclusive quando a decisão for não comunicar.
7. Corrigir a causa e anotar o que muda no produto.

## Conteúdo mínimo da comunicação

Descrição do incidente, dados atingidos, titulares quando souber, medidas técnicas já usadas, riscos aos titulares, medidas de mitigação, data do fato quando existir, data do conhecimento e canal de contato. O contato do encarregado entra quando a nomeação existir.

## Limite

Este plano não foi exercitado em simulado. A direção ainda precisa indicar quem protocola.

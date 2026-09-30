# Relatório de impacto à proteção de dados pessoais (RIPD)

Relatório de impacto do tratamento de telemetria de saúde do piloto Saúde Responsiva, para o art. 38 da LGPD. Descreve o que o repositório faz e o risco que permanece. Não declara risco baixo e não dispensa a assinatura da direção.

## Tratamento

O companion coleta frequência cardíaca, SpO2, pressão e temperatura, com identificador do paciente, e envia à API secure. A matriz de regras devolve alerta como apoio à decisão, sem conduta obrigatória. O painel mostra o resultado a quem tem chave e escopo.

A necessidade do piloto é ter o sinal vital para esse alerta. Sem o sinal, o alerta não existe. O laboratório (TCN, conformal, Language v1) fica fora deste relatório.

## Base e titulares

Titulares são os pacientes do piloto. A base que o app exige é o consentimento específico do art. 11, I, registrado no aparelho. Controlador e encarregado não estão nomeados aqui.

## Medidas que o código já tem

Chave comparada com `hmac.compare_digest`, escopos de escrita, leitura e admin, trava por paciente, cabeçalhos, rate limit, preferências cifradas no companion, teto de 100 amostras em memória, exclusão administrativa que alcança memória, frota e revisão de piloto, e trilha sem o identificador cru.

## Riscos

- Dado sensível de saúde fora do controle exclusivo do aparelho, porque o ingest sai para a API.
- A nuvem apontada está em `us-central1`, sem mecanismo do art. 33. Este é o risco residual alto.
- Não há encarregado publicado para o titular procurar.
- O titular não confirma, acessa, corrige nem exporta os dados por conta própria. A eliminação depende de um admin.
- Linhas antigas de log podem ainda ter o identificador até o coletor expirar.

## Conclusão

O tratamento segue necessário para o alerta do piloto e passa a depender do consentimento no app. O risco residual da transferência internacional permanece alto enquanto a região for `us-central1` sem instrumento do art. 33. A direção precisa decidir a migração para `southamerica-east1` ou o instrumento, nomear o encarregado e assinar este RIPD. Até lá, este texto é a avaliação, não o ato da direção.

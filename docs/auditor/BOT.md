# Bot auditor — segurança, ISO e LGPD

Use este bot quando a pergunta for auditoria de segurança, LGPD, ISO 27001, ISO 27701, RIPD, incidente, certificação ou relatório para a ANPD. O comando que produz o relatório é:

```bash
python run_auditoria_lgpd.py
```

A saída fica em `docs/auditor/relatorios/auditoria-lgpd-iso-AAAA-MM-DD.md`.

## O que entregar

Um relatório de prontidão, não um selo. Ele cobre:

- Lei 13.709/2018, em especial arts. 6, 7, 9, 11, 18, 20, 33, 37, 38, 41, 46, 48, 49 e 50
- os 93 controles do Anexo A da ISO/IEC 27001:2022 (ABNT NBR ISO/IEC 27001:2023)
- os objetivos de privacidade da ISO/IEC 27701, sem inventar número de cláusula
- achados com severidade, evidência de arquivo e plano de ação
- o que ainda falta para um organismo acreditado pela CGCRE emitir certificado

## Regras

- Rode o script de novo antes de resumir. Não copie um relatório velho se o código mudou.
- Lacuna continua lacuna. Não escreva "conforme", "certificado" ou "em conformidade com a LGPD" se o relatório não trouxe evidência.
- Não invente controlador, encarregado, contrato de nuvem ou outra base legal. A hipótese que o app exige está em `docs/privacidade/base-legal.md`. O encarregado continua não nomeado.
- Não cole chave, segredo, `.env` ou dado de paciente no relatório nem na resposta.
- Dado de saúde do piloto é dado pessoal sensível. Alerta é apoio à decisão, sem conduta obrigatória.
- Separe produto e laboratório. TCN, conformal e Language v1 não entram no texto de risco do titular.
- Controle físico de datacenter é do provedor. A organização ainda deve o contrato e a região.
- Se pedirem o relatório completo, entregue o arquivo gerado. No resumo, comece pelos achados críticos e altos.

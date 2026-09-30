# Relatório de auditoria interna — segurança e LGPD

**Organização:** Next2U Saúde / produto Saúde Responsiva (Healthtech)
**Escopo:** repositório `healthtech`, caminho crítico companion → ingest → alertas → painel, mais lacunas de governança que o código não cobre
**Data:** 2026-09-28
**Revisão git:** `51478b6` na branch `main`
**Normas de referência:** Lei 13.709/2018 (LGPD); ISO/IEC 27001:2022 Anexo A (adotada no Brasil como ABNT NBR ISO/IEC 27001:2023); objetivos de privacidade da ISO/IEC 27701
**Tipo:** auditoria interna de prontidão. Este documento não é certificação ISO, não é selo, não é parecer jurídico e não declara o tratamento regular perante a ANPD.

## 1. Como ler este relatório

Situação de cada controle:

- **Evidenciado no repositório** — o código ou o documento citado sustenta o controle.
- **Parcial** — há um pedaço e falta outro exigido pela norma.
- **Lacuna** — o controle se aplica ao produto e a evidência não foi encontrada.
- **Pendente de evidência externa** — política, contrato, treinamento ou ato da direção, fora deste repositório.
- **Responsabilidade do provedor** — controle físico de datacenter, a cargo de quem opera a nuvem. A organização ainda precisa do contrato e da região.

Um controle sem evidência permanece lacuna. O auditor não promove lacuna a conformidade.

## 2. Escopo do tratamento

O produto trata telemetria de saúde: frequência cardíaca, variabilidade, temperatura, SpO2, pressão e identificador do paciente, vindos de pulseira ou perfil Bluetooth, pelo companion Android, até `POST /api/v1/wearables/ingest` na API secure, matriz de alertas e painel.

Isso é dado pessoal sensível (LGPD art. 5, II). O laboratório (TCN, conformal, Language v1, hemodinâmica) não entra na resposta do piloto e fica fora do escopo desta auditoria de produto, salvo se um deploy passar a expô-lo.

Papéis que a auditoria precisa receber da direção, e que este repositório não fixa: quem é o controlador, quem é o operador (em especial o provedor de nuvem) e quem é o encarregado.

## 3. Resumo

| Quadro | Evidenciado | Parcial | Lacuna | Evidência externa | Provedor |
|---|---:|---:|---:|---:|---:|
| LGPD | 10 | 2 | 2 | 0 | 0 |
| ISO/IEC 27001:2022 Anexo A (93 controles) | 21 | 0 | 1 | 57 | 14 |

Achados críticos: 1. Achados altos: 1. O produto não está pronto para certificação ISO/IEC 27001 nem para um relatório de conformidade LGPD fechado. O repositório sustenta o controle técnico da API, o consentimento no companion, a exclusão além da memória, o plano de incidente, o registro de operações, o RIPD e a retenção. Seguem abertos a região `us-central1` e a nomeação do encarregado.

## 4. Inventário mínimo do tratamento

| Item | O que o repositório mostra |
|---|---|
| Titulares | Pacientes do piloto, identificados por `patient_id` |
| Dados | Telemetria vital, identificador de dispositivo, origem do ingest (HTTP, BLE simulado, BLE físico) |
| Operação | Coleta no companion depois do consentimento, ingestão, alerta por regra, exibição no painel e exclusão admin da telemetria, da frota, da revisão de piloto e do cadastro quando há banco |
| Operadores técnicos | API secure, companion, nuvem na região citada pelo ledger (`us-central1`) |
| Decisão automatizada | Alerta com `decision_support`, sem conduta obrigatória |
| O que não está escrito | encarregado e canal do titular, mecanismo de transferência internacional, acesso, correção e portabilidade pelo titular |

## 5. Achados

### F-03 — crítico: Tratamento em us-central1 sem mecanismo de transferência

O projeto de nuvem está em us-central1. Dado pessoal sensível fora do Brasil exige uma das hipóteses do art. 33. Não há cláusulas, garantia ou registro dessa escolha.

Referências: LGPD art. 33, ISO/IEC 27001:2022 A.5.23, src/ops/gcp_billing_sim.py.

### F-06 — alto: Encarregado não nomeado nos documentos do produto

O art. 41 exige encarregado divulgado, de forma pública, de preferência no site. O repositório não tem nome, canal nem ato de nomeação.

Referências: LGPD art. 41.


## 6. LGPD — prontidão por artigo

| ID | Controle | Aplicabilidade | Situação |
|---|---|---|---|
| Art. 6 | Princípios: finalidade, necessidade, segurança, prevenção e responsabilização | produto | Evidenciado no repositório |
| Art. 7 | Base legal para dado pessoal | produto | Evidenciado no repositório |
| Art. 11 | Base legal para dado pessoal sensível de saúde | produto | Evidenciado no repositório |
| Art. 9 | Informação ao titular quando o tratamento se apoia em consentimento | produto | Evidenciado no repositório |
| Art. 18 | Direitos do titular: confirmação, acesso, correção, portabilidade, eliminação e revogação | produto | Parcial |
| Art. 20 | Revisão de decisão automatizada | produto | Evidenciado no repositório |
| Art. 33 | Transferência internacional | produto | Lacuna |
| Art. 37 | Registro das operações de tratamento | produto | Evidenciado no repositório |
| Art. 38 | Relatório de impacto à proteção de dados | produto | Evidenciado no repositório |
| Art. 41 | Encarregado pelo tratamento | produto | Lacuna |
| Art. 46 | Medidas de segurança | produto | Evidenciado no repositório |
| Art. 48 | Comunicação de incidente de segurança | produto | Evidenciado no repositório |
| Art. 49 | Sistemas estruturados para segurança e privacidade desde a concepção | produto | Evidenciado no repositório |
| Art. 50 | Boas práticas e governança | produto | Parcial |

A exclusão admin alcança a telemetria em memória, a frota, a revisão de piloto e o cadastro operacional quando o banco existe. Confirmação, acesso, correção e portabilidade ainda não são fluxo do titular. Revogar o consentimento no companion interrompe a coleta nova.

## 7. Declaração de aplicabilidade — ISO/IEC 27001:2022 Anexo A

Títulos em português de trabalho, alinhados ao Anexo A. A SoA que for para um organismo de certificação deve usar a redação da ABNT NBR ISO/IEC 27001:2023 e a justificativa de não aplicabilidade assinada pela direção. Nenhum controle abaixo foi marcado como não aplicável: ou há evidência, ou fica pendente.

| ID | Controle | Aplicabilidade | Situação |
|---|---|---|---|
| A.5.1 | Políticas de segurança da informação | organizacao | Pendente de evidência externa |
| A.5.2 | Papéis e responsabilidades de segurança da informação | organizacao | Pendente de evidência externa |
| A.5.3 | Segregação de funções | organizacao | Pendente de evidência externa |
| A.5.4 | Responsabilidades da direção | organizacao | Pendente de evidência externa |
| A.5.5 | Contato com autoridades | organizacao | Pendente de evidência externa |
| A.5.6 | Contato com grupos de interesse especial | organizacao | Pendente de evidência externa |
| A.5.7 | Inteligência de ameaças | organizacao | Pendente de evidência externa |
| A.5.8 | Segurança da informação na gestão de projetos | organizacao | Pendente de evidência externa |
| A.5.9 | Inventário de ativos de informação | organizacao | Pendente de evidência externa |
| A.5.10 | Uso aceitável de ativos de informação | organizacao | Pendente de evidência externa |
| A.5.11 | Devolução de ativos | organizacao | Pendente de evidência externa |
| A.5.12 | Classificação da informação | organizacao | Pendente de evidência externa |
| A.5.13 | Rotulagem da informação | organizacao | Pendente de evidência externa |
| A.5.14 | Transferência da informação | organizacao | Pendente de evidência externa |
| A.5.15 | Controle de acesso | produto | Evidenciado no repositório |
| A.5.16 | Gestão de identidades | organizacao | Pendente de evidência externa |
| A.5.17 | Informação de autenticação | produto | Evidenciado no repositório |
| A.5.18 | Direitos de acesso | organizacao | Pendente de evidência externa |
| A.5.19 | Segurança da informação nas relações com fornecedores | organizacao | Pendente de evidência externa |
| A.5.20 | Segurança da informação em acordos com fornecedores | organizacao | Pendente de evidência externa |
| A.5.21 | Segurança da cadeia de suprimento de TIC | organizacao | Pendente de evidência externa |
| A.5.22 | Monitoramento e mudança de serviços de fornecedores | organizacao | Pendente de evidência externa |
| A.5.23 | Segurança da informação no uso de serviços em nuvem | produto | Lacuna |
| A.5.24 | Planejamento e preparação para incidentes | produto | Evidenciado no repositório |
| A.5.25 | Avaliação e decisão sobre eventos de segurança | produto | Evidenciado no repositório |
| A.5.26 | Resposta a incidentes de segurança da informação | produto | Evidenciado no repositório |
| A.5.27 | Aprendizado com incidentes | organizacao | Pendente de evidência externa |
| A.5.28 | Coleta de evidências | organizacao | Pendente de evidência externa |
| A.5.29 | Segurança da informação durante disrupção | organizacao | Pendente de evidência externa |
| A.5.30 | Prontidão de TIC para continuidade | organizacao | Pendente de evidência externa |
| A.5.31 | Requisitos legais, estatutários, regulatórios e contratuais | organizacao | Pendente de evidência externa |
| A.5.32 | Direitos de propriedade intelectual | organizacao | Pendente de evidência externa |
| A.5.33 | Proteção de registros | produto | Evidenciado no repositório |
| A.5.34 | Privacidade e proteção de PII | produto | Evidenciado no repositório |
| A.5.35 | Revisão independente da segurança da informação | organizacao | Pendente de evidência externa |
| A.5.36 | Conformidade com políticas e normas | organizacao | Pendente de evidência externa |
| A.5.37 | Procedimentos operacionais documentados | organizacao | Pendente de evidência externa |
| A.6.1 | Verificação de antecedentes | organizacao | Pendente de evidência externa |
| A.6.2 | Termos e condições de contratação | organizacao | Pendente de evidência externa |
| A.6.3 | Conscientização, educação e treinamento | organizacao | Pendente de evidência externa |
| A.6.4 | Processo disciplinar | organizacao | Pendente de evidência externa |
| A.6.5 | Responsabilidades após desligamento ou mudança | organizacao | Pendente de evidência externa |
| A.6.6 | Acordos de confidencialidade | organizacao | Pendente de evidência externa |
| A.6.7 | Trabalho remoto | organizacao | Pendente de evidência externa |
| A.6.8 | Comunicação de eventos de segurança da informação | organizacao | Pendente de evidência externa |
| A.7.1 | Perímetros de segurança física | provedor | Responsabilidade do provedor |
| A.7.2 | Entrada física | provedor | Responsabilidade do provedor |
| A.7.3 | Proteção de escritórios, salas e instalações | provedor | Responsabilidade do provedor |
| A.7.4 | Monitoramento de segurança física | provedor | Responsabilidade do provedor |
| A.7.5 | Proteção contra ameaças físicas e ambientais | provedor | Responsabilidade do provedor |
| A.7.6 | Trabalho em áreas seguras | provedor | Responsabilidade do provedor |
| A.7.7 | Mesa limpa e tela limpa | provedor | Responsabilidade do provedor |
| A.7.8 | Posicionamento e proteção de equipamentos | provedor | Responsabilidade do provedor |
| A.7.9 | Segurança de ativos fora das instalações | provedor | Responsabilidade do provedor |
| A.7.10 | Mídias de armazenamento | provedor | Responsabilidade do provedor |
| A.7.11 | Utilidades de suporte | provedor | Responsabilidade do provedor |
| A.7.12 | Segurança do cabeamento | provedor | Responsabilidade do provedor |
| A.7.13 | Manutenção de equipamentos | provedor | Responsabilidade do provedor |
| A.7.14 | Descarte ou reuso seguro de equipamentos | provedor | Responsabilidade do provedor |
| A.8.1 | Dispositivos endpoint de usuário | organizacao | Pendente de evidência externa |
| A.8.2 | Direitos de acesso privilegiado | produto | Evidenciado no repositório |
| A.8.3 | Restrição de acesso à informação | produto | Evidenciado no repositório |
| A.8.4 | Acesso ao código-fonte | organizacao | Pendente de evidência externa |
| A.8.5 | Autenticação segura | produto | Evidenciado no repositório |
| A.8.6 | Gestão de capacidade | organizacao | Pendente de evidência externa |
| A.8.7 | Proteção contra malware | organizacao | Pendente de evidência externa |
| A.8.8 | Gestão de vulnerabilidades técnicas | organizacao | Pendente de evidência externa |
| A.8.9 | Gestão de configuração | organizacao | Pendente de evidência externa |
| A.8.10 | Eliminação da informação | produto | Evidenciado no repositório |
| A.8.11 | Mascaramento de dados | produto | Evidenciado no repositório |
| A.8.12 | Prevenção de vazamento de dados | organizacao | Pendente de evidência externa |
| A.8.13 | Backup da informação | organizacao | Pendente de evidência externa |
| A.8.14 | Redundância das instalações de processamento | organizacao | Pendente de evidência externa |
| A.8.15 | Registro de logs | produto | Evidenciado no repositório |
| A.8.16 | Atividades de monitoramento | organizacao | Pendente de evidência externa |
| A.8.17 | Sincronização de relógios | organizacao | Pendente de evidência externa |
| A.8.18 | Uso de programas utilitários privilegiados | organizacao | Pendente de evidência externa |
| A.8.19 | Instalação de software em sistemas operacionais | organizacao | Pendente de evidência externa |
| A.8.20 | Segurança de redes | produto | Evidenciado no repositório |
| A.8.21 | Segurança de serviços de rede | organizacao | Pendente de evidência externa |
| A.8.22 | Segregação de redes | organizacao | Pendente de evidência externa |
| A.8.23 | Filtragem web | organizacao | Pendente de evidência externa |
| A.8.24 | Uso de criptografia | produto | Evidenciado no repositório |
| A.8.25 | Ciclo de vida de desenvolvimento seguro | produto | Evidenciado no repositório |
| A.8.26 | Requisitos de segurança de aplicação | produto | Evidenciado no repositório |
| A.8.27 | Arquitetura e princípios de engenharia seguros | organizacao | Pendente de evidência externa |
| A.8.28 | Codificação segura | produto | Evidenciado no repositório |
| A.8.29 | Testes de segurança em desenvolvimento e aceitação | produto | Evidenciado no repositório |
| A.8.30 | Desenvolvimento terceirizado | organizacao | Pendente de evidência externa |
| A.8.31 | Separação de ambientes de desenvolvimento, teste e produção | produto | Evidenciado no repositório |
| A.8.32 | Gestão de mudanças | organizacao | Pendente de evidência externa |
| A.8.33 | Informação de teste | produto | Evidenciado no repositório |
| A.8.34 | Proteção de sistemas durante testes de auditoria | organizacao | Pendente de evidência externa |

Controles físicos (A.7) estão com o provedor de datacenter. A organização continua responsável pelo escritório, pelo descarte de mídia e pelo contrato que cobre essa parte.

## 8. ISO/IEC 27701 — objetivos de privacidade

A ISO/IEC 27701 estende o sistema de gestão para privacidade. Aqui os objetivos estão sem número de cláusula de uma edição específica, para não inventar numeração. Uma certificação PIMS usa a edição vigente no organismo acreditado e a SoA de privacidade correspondente.

| ID | Controle | Aplicabilidade | Situação |
|---|---|---|---|
| PIMS-01 | Identificar finalidade e base legal do tratamento | produto | Evidenciado no repositório |
| PIMS-02 | Registrar consentimento ou outra base, e a informação dada ao titular | produto | Evidenciado no repositório |
| PIMS-03 | Atender direitos do titular, inclusive eliminação | produto | Parcial |
| PIMS-04 | Privacidade desde a concepção e por padrão | produto | Evidenciado no repositório |
| PIMS-05 | Contrato com operador e serviços em nuvem | produto | Lacuna |
| PIMS-06 | Transferência internacional de PII | produto | Lacuna |
| PIMS-07 | Avaliação de impacto à privacidade | produto | Evidenciado no repositório |
| PIMS-08 | Ponto de contato de privacidade (encarregado) | produto | Lacuna |

## 9. O que uma certificação ainda exige e este relatório não substitui

1. Escopo escrito do sistema de gestão, aprovado pela direção.
2. Análise de riscos e plano de tratamento, com dono e prazo.
3. SoA completa, com justificativa do que for excluído.
4. Políticas de controle de acesso, criptografia, backup, classificação e mesa limpa.
5. Contratos com operadores, inclusive o provedor de nuvem, e o mecanismo do art. 33.
6. Nomeação pública do encarregado e canal do titular.
7. RIPD do tratamento de saúde e registro do art. 37.
8. Procedimento de incidente testado, com comunicação à ANPD e ao titular.
9. Auditoria interna independente e análise crítica da direção.
10. Auditoria de certificação por organismo acreditado pela CGCRE. Este arquivo não é esse certificado.

## 10. Plano de ação sugerido

| Ordem | Ação | Fecha |
|---|---|---|
| 1 | Tratamento em us-central1 sem mecanismo de transferência | F-03 |
| 2 | Encarregado não nomeado nos documentos do produto | F-06 |

## 11. Evidências coletadas nesta execução

- `purge_endpoint` (sim): Há exclusão de histórico com escopo admin. Evidência: `saude_responsiva_secure/app/api/lgpd.py`.
- `purge_durable` (sim): A exclusão alcança a telemetria, a frota e a revisão de piloto. Evidência: `saude_responsiva_secure/app/services/telemetry_store.py`.
- `fhir_deid` (sim): Há descaracterização de recurso FHIR Patient (nome, contato, identificador com hash). Evidência: `src/security/anonymization.py`.
- `audit_log` (sim): A API registra acesso com chave mascarada e X-Request-ID. Evidência: `saude_responsiva_secure/app/services/audit.py`, `saude_responsiva_secure/app/main.py`.
- `audit_minimized` (sim): A trilha não grava o identificador cru do paciente. Evidência: `saude_responsiva_secure/app/services/audit.py`.
- `hmac_auth` (sim): A chave de API é comparada com hmac.compare_digest, sem casar por prefixo. Evidência: `saude_responsiva_secure/app/security/auth.py`.
- `scopes` (sim): Há três escopos: escrita, leitura e admin. Evidência: `saude_responsiva_secure/app/security/auth.py`.
- `patient_authz` (sim): Há trava por paciente. Em produção, sem lista autorizada, o acesso cruzado é negado. Evidência: `saude_responsiva_secure/app/security/auth.py`.
- `headers` (sim): HSTS, CSP, nosniff, frame deny e Permissions-Policy estão no middleware. Evidência: `saude_responsiva_secure/app/security/headers.py`.
- `rate_limit` (sim): Rate limit está ligado na aplicação secure. Evidência: `saude_responsiva_secure/app/security/rate_limit.py`, `saude_responsiva_secure/app/main.py`.
- `security_tests` (sim): A suíte secure cobre 401, escopo, cabeçalhos, trilha, rate limit, anti-IDOR e purga. Evidência: `saude_responsiva_secure/test_security.py`.
- `gitignore_secrets` (sim): .env, keystore e pem estão no gitignore. Evidência: `.gitignore`.
- `env_untracked` (sim): .env não está no índice do git. Evidência: `.gitignore`.
- `encrypted_prefs` (sim): A chave de ingestão do companion fica em EncryptedSharedPreferences. Evidência: `companion-android/app/src/main/java/com/healthtech/companion/data/AppPrefs.kt`.
- `consent_ui` (sim): Há tela de consentimento no companion. Evidência: `companion-android/app/src/main/java/com/healthtech/companion/ui/MainViewModel.kt`, `companion-android/app/src/main/java/com/healthtech/companion/ui/MainScreen.kt`, `companion-android/app/src/main/java/com/healthtech/companion/data/ConsentNotice.kt`, `companion-android/app/src/main/java/com/healthtech/companion/data/AppPrefs.kt`.
- `holder_notice` (sim): O app informa que o alerta é apoio à decisão, sem conduta obrigatória. Evidência: `companion-android/app/src/main/java/com/healthtech/companion/ui/MainScreen.kt`.
- `legal_basis` (sim): A hipótese do art. 11 exigida pelo app é o consentimento específico. Evidência: `docs/privacidade/base-legal.md`.
- `holder_rights` (não): Confirmação, acesso, correção e portabilidade não têm fluxo do titular. Evidência: `saude_responsiva_secure/app/api/lgpd.py`.
- `incident_procedure` (sim): Há procedimento de comunicação de incidente à ANPD e ao titular. Evidência: `docs/privacidade/incidente-seguranca.md`.
- `ropa` (sim): Há registro das operações de tratamento (art. 37). Evidência: `docs/privacidade/registro-operacoes.md`.
- `ripd` (sim): Há relatório de impacto à proteção de dados (art. 38). Evidência: `docs/privacidade/ripd.md`.
- `dpo` (não): Não há nomeação de encarregado no repositório (art. 41). Evidência: `docs/privacidade/encarregado.md`.
- `retention` (sim): Há política de retenção e descarte. Evidência: `docs/privacidade/registro-operacoes.md`, `docs/privacidade/retencao.md`.
- `cloud_region` (não): O faturamento do projeto aponta us-central1. Dado de saúde fora do Brasil é transferência internacional. Evidência: `src/ops/gcp_billing_sim.py`.
- `transfer_mechanism` (não): Não há cláusulas, decisão de adequação nem garantia do art. 33 em vigor. Evidência: `docs/privacidade/transferencia-internacional.md`.
- `decision_support` (sim): O piloto declara que o alerta é apoio à decisão, sem conduta obrigatória. Evidência: `AGENTS.md`.
- `auth_prod_lock` (sim): AUTH_DISABLED não permanece ligado quando o ambiente é produção. Evidência: `saude_responsiva_secure/app/config.py`.
- `weak_keys` (sim): Há lista de chaves fracas e bloqueio associado à produção. Evidência: `saude_responsiva_secure/app/security/auth.py`.
- `lgpd_module` (sim): Existe módulo de endpoint LGPD. Isso não substitui política, base legal nem RIPD. Evidência: `saude_responsiva_secure/app/api/lgpd.py`.

## 12. Limite

A coleta olha o código e os markdown deste repositório. Não entrevista a direção, não lê contrato com a nuvem, não testa produção e não acessa dado de paciente. Onde a evidência falta, a situação permanece lacuna ou pendência. Repetir a auditoria: `python run_auditoria_lgpd.py`.

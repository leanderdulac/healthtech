# Política de retenção e descarte

Prazo de retenção do que o código do Saúde Responsiva realmente guarda. Onde o prazo depende do provedor, isso fica dito. Não há guarda longa de telemetria além dos limites abaixo.

## Telemetria vital

`history_max_per_patient` é 100 em `saude_responsiva_secure/app/config.py`. Cada paciente fica com no máximo 100 amostras, só na memória do processo. A amostra que passa do teto é descartada na hora. O processo que reinicia descarta o restante. O `DELETE /api/v1/patient/{id}/anonymize`, com escopo admin, apaga o que ainda estiver na memória.

## Frota de relógios

`data/ops/fleet_devices.json` e, quando o bucket está configurado, o objeto `ops/fleet/devices.json`. A linha do paciente sai no mesmo DELETE, e o arquivo é regravado sem ela.

## Revisão de piloto

`data/pilot_review/events.jsonl` guarda o evento da regra até o mesmo DELETE. Não há segunda cópia de longo prazo neste repositório.

## Cadastro operacional

Quando `DATABASE_URL` existe, o mesmo DELETE apaga a linha daquele `patient_id` em `enrollments` (nome, telefone, cuidador). Sem essa variável, não há linha para apagar.

## Trilha de acesso

A aplicação não grava trilha própria em disco. A linha vai para o stdout, com a chave mascarada e o trecho do caminho depois de `/patient/` substituído por `redigido`. O prazo efetivo é o do coletor de log. No Cloud Logging, o bucket `_Default` retém 30 dias salvo configuração diferente do projeto. Este repositório não comprova a configuração do projeto `healthtech-gcp-2026`. Linhas antigas, emitidas antes desta redação, podem ainda ter o identificador até o coletor expirar.

## Registro de incidente

Cinco anos, contados do registro, conforme a Resolução CD/ANPD nº 15/2024. Esse prazo é o do procedimento em `incidente-seguranca.md`, não o da telemetria.

## Descarte

Eliminação do titular no servidor é o DELETE administrativo. Revogar o consentimento no companion para a coleta nova e apaga a outbox local. Não apaga, sozinho, o que a API já gravou.

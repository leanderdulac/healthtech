# Catálogo e ingestão medida — proposta R2

Status: **PROPOSTA PARA REVISÃO**, sem liberação clínica ou implantação.
Base de desenvolvimento: `main@be44b6c913c50ce67dc85d46d29f1739439c4485`.

## Identidade do catálogo

A regra de promoção do §4 permite combinações sem linha no catálogo de 971
padrões: alto/3 estrelas e crítico/1 estrela nas 43 bases originalmente de uma
estrela. A extensão acrescenta 86 linhas, preservando os 971 registros e IDs
originais. Usa `.8` para alto/3 e `.9` para crítico/1; não renumera `.1`–`.7`.

As 12 lacunas observadas anteriormente são os dois pares das bases 011, 016,
022, 030, 052 e 103. As outras 74 são a mesma lacuna estrutural nas demais
bases de uma estrela. Nenhum limiar fisiológico é criado por essas linhas.

O lookup exige uma única correspondência de base, faixa e estrelas. Não usa
fallback de outra faixa ou um ID `.x`. Catálogo ausente/incompleto não pode
substituir as gravidades por defaults leves. O arquivo acompanha o vendor da
imagem secure; o build verifica o caso conhecido SpO2 88/FC 72 → n2u_034 crítico.

A regra 078 segue o literal ≥400 sem teto 600 oculto. A 079 continua disparando
≥600; o desempate por maior gravidade e primeiro hit continua o da R3.
Os 51 casos-base R3 permanecem fixados no teste existente.

## Adaptador e API

- A API continua exigindo HR medida. Um envelope parcial sem HR preserva as
  métricas Bronze, mas não produz body de ingestão. PPG não é HR; o caminho
  PPG sem medição separada gera erro explícito, em vez de fabricar 70 bpm.
- `client_reading_id` estável e `ingest_source` são preservados pelo adaptador.
  Reenvios na API local devem devolver o mesmo `reading_id` como `duplicate`.
- Timestamp fornecido ao adaptador precisa de fuso; formatos equivalentes
  são normalizados em UTC. Sem timestamp, não se fabrica um novo instante de
  medição no retry. A API pode registrar seu próprio instante de recepção.
- `skin_temp` fica separado de `body_temp_c`. Só temperatura corporal
  explicitamente fornecida alimenta `VitalSnapshot.temp_c`. Este campo não
  afirma que um modelo específico de pulseira mede temperatura corporal.

## Limites e dependências preservadas

Os testes usam exclusivamente dados fictícios locais. Simulação do layout da
imagem não é execução de Docker. SQLite local não comprova Cloud SQL nem
PostgreSQL; os testes existentes de PostgreSQL continuam exigindo esse serviço.

Fórmula/versionamento de basal, janela de sono/passos, qualidade, cobertura,
timezone do dispositivo e prova de capacidade física continuam dependendo de
fonte específica. Defaults de laboratório não satisfazem esses contratos.
Uma API saudável ou um esquema HTTP acessível não prova isolamento do banco
nem autoriza enviar leituras a uma revisão publicada.

A extensão de catálogo não substitui uma matriz histórica de 1.942 referências
por 2.114 referências, nem aprova conversas clínicas adicionais. Fluxos de
WhatsApp, seus contextos e suas versões já validadas não são alterados aqui.

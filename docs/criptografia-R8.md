# R8 — criptografia dos dados de saúde (Core FastAPI)

Documento para o go-live Next2U (30/11/2026). Descreve o que o serviço
`healthtech-secure-api` (Cloud Run, projeto `healthtech-gcp-2026`,
Postgres no Cloud SQL `healthtech-pg`) faz com dados em trânsito e em
repouso. Não é certificado, laudo ou política de privacidade.

A cifra de campos **nasce desligada**. Sem `FIELD_ENCRYPTION_KEY`, a API
grava e lê como hoje. Ligar a chave, aplicar a migração `005` e rodar o
backfill são passos separados e precisam do OK do Leandro. Este PR não
faz deploy e não escreve em produção.

## 1. O que a auditoria encontrou

### Em trânsito

| Trecho | Estado |
|---|---|
| Cliente (Android/iOS) → Cloud Run | HTTPS termina no front do Cloud Run. A API não escuta TLS sozinha; o healthcheck interno usa `http://127.0.0.1`. |
| Resposta HTTP | `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` em `saude_responsiva_secure/app/security/headers.py`, em toda resposta, inclusive `/api/health`. |
| API → Cloud SQL por TCP público | `ensure_database_sslmode` coloca `sslmode=require` se a URL não tiver `require`, `verify-ca` ou `verify-full`. `disable` / `allow` / `prefer` em host remoto sobem para `require`. |
| API → Cloud SQL por socket `/cloudsql/...` | Sem `sslmode`. O conector do Cloud Run abre o túnel; o socket Unix local não fala TLS. É o formato do `.env.example`. |
| Postgres em `localhost` / `127.0.0.1` | Sem imposição de TLS, para o teste local. |

### Em repouso, antes desta camada

Tabela `wearable_readings` (ingest e `batch-ingest`): `patient_id`,
`device_id` (pode ser MAC), `reported_patient_id`, `value` (vital numérico),
`extra` e `frame` (JSON com telemetria, id do paciente e id do aparelho)
estavam em claro. Dedup por `client_reading_id`, `Idempotency-Key` e chave
natural (`patient_id + device_id + timestamp + métrica`).

Tabela `wearable_device_last_vitals`: SpO₂, passos e pressão em
`DOUBLE PRECISION`, chave `device_id`.

Tabela `device_patient_overrides`: `device_id` e `patient_id` em claro
(vínculo canônico usado na ingestão).

Tabela `enrollments` (cadastro; este serviço só lê e apaga): `display_name`,
`phone`, `caregiver_phone`, `diseases` em claro. `patient_id` é a chave
primária das consultas autorizadas.

### API keys

Não ficam no Postgres. `API_KEY`, `ADMIN_API_KEY`, `INGEST_API_KEY`,
`READ_API_KEY` e `SMCLICK_READ_API_KEY` são segredos de ambiente (Secret
Manager no Cloud Run). A comparação é `hmac.compare_digest` sobre o valor
inteiro, sem prefix match. Não há hash no banco porque a chave não é uma
coluna: o processo precisa do segredo que o app envia no header
`X-API-Key`. Log de auditoria usa chave mascarada.

## 2. O que passa a ser cifrado (quando a chave está ligada)

Algoritmo: **AES-256-GCM**. Cada valor leva o key id, para rotação:

```text
enc1:<key_id>:<nonce>:<ciphertext>
```

O JSON de leitura continua sendo JSON válido, para as colunas `json`/`jsonb`
que já existem:

```text
{"_enc":"enc1:v1:..."}
```

O AAD amarra o ciphertext ao campo (`wearable.frame`, `enrollment.phone`,
etc.). Trocar o blob de coluna não abre.

| Dado | Onde fica | Como a API ainda busca |
|---|---|---|
| Frame e extra da leitura (vitais, ids, telemetria) | `wearable_readings.frame` / `.extra` | A resposta decripta. O contrato de ingest não muda. |
| Vital numérico solto | `value` vai a `NULL` | O número continua dentro do frame cifrado. |
| `patient_id`, `device_id`, `reported_patient_id` e a chave natural | coluna vira índice cego `bi1.` + HMAC-SHA256 | `WHERE coluna = :claro OR coluna = :bi1` acha legado e novo. |
| Nome, telefone, telefone do cuidador, doenças | `enrollments` (após o backfill) | Leitura decripta. `patient_id` da tabela continua em claro: é a chave do `WHERE` de autorização. Quem grava o cadastro fora deste serviço precisa passar a usar a mesma cifra, senão linhas novas voltam em claro. |
| SpO₂, passos, pressão do snapshot | colunas `*_enc` **depois** da migração 005 | Sem a 005, o snapshot segue em claro (cache derivado). Com a 005, o `DOUBLE` fica `NULL` e a leitura decripta. |
| MAC e paciente do vínculo device→paciente | `device_id_enc` / `patient_id_enc` **depois** da 005; a PK vira `bi1.` | Sem a 005, o vínculo segue em claro para não perder o id reversível. |

Ficam em claro de propósito, mesmo com a chave ligada:

- `client_reading_id` e `Idempotency-Key` (correlação técnica da outbox; o dedup do app depende deles).
- timestamps (`measured_at`, `received_at`) — a ordenação e o índice único precisam deles.
- `device_label` (rótulo operacional do aparelho, não o nome da pessoa).
- `metric_type` e `unit` (`heart_rate`, `bpm`).
- `patient_id` em `enrollments` (chave de autorização e de join).
- API keys (ambiente, não coluna).

Linha antiga sem prefixo `enc1` / `bi1` é lida como está. A resposta da API
continua com o id e o vital em claro para o cliente autorizado. O app
(Ktor, OkHttp, iOS) não muda payload, header nem código de status.

## 3. Chaves

Não cole o valor em git, em PR, em log ou neste documento.

```bash
# DEK — 32 bytes. Secret Manager → env FIELD_ENCRYPTION_KEY no Cloud Run.
openssl rand -base64 32

# Índice cego. Obrigatória em production/staging se a DEK existir.
# Rotacionar a DEK NÃO pode trocar esta chave, senão o bi1. muda e a busca quebra.
openssl rand -base64 32
```

| Env | Papel |
|---|---|
| `FIELD_ENCRYPTION_KEY` | DEK ativa (base64 ou hex de 64 chars). Vazia = cifra desligada. |
| `FIELD_ENCRYPTION_KEY_ID` | Id gravado no token. Default `v1`. |
| `FIELD_ENCRYPTION_KEYS` | Chaves antigas só para leitura: `v1:<material>,v2:<material>`. |
| `FIELD_BLIND_INDEX_KEY` | HMAC do índice cego. Separada da DEK. |
| `FIELD_ENCRYPTION_KMS_KEY` | Opcional. Resource name da chave Cloud KMS. Aí `FIELD_ENCRYPTION_KEY` é a DEK **embrulhada** (base64 do ciphertext KMS), desempacotada uma vez no boot. Exige `google-cloud-kms` na imagem; sem o pacote o boot falha fechado. O nome sugerido é `projects/healthtech-gcp-2026/locations/us-central1/keyRings/healthtech/cryptoKeys/field-dek` — a chave em si não é criada por este PR. |

Em desenvolvimento, se `FIELD_BLIND_INDEX_KEY` faltar, o índice deriva da DEK
por HKDF. Isso não vale para produção: o boot recusa a DEK sem a chave do índice.

## 4. Rotação

1. Gerar a DEK nova (`openssl rand -base64 32`). Não mexer em `FIELD_BLIND_INDEX_KEY`.
2. Publicar `FIELD_ENCRYPTION_KEY` com o material novo e `FIELD_ENCRYPTION_KEY_ID=v2`.
3. Manter a DEK antiga em `FIELD_ENCRYPTION_KEYS=v1:<material-antigo>`.
4. Deploy. Leituras `enc1:v1:` abrem com a chave antiga. Escrita nova sai `enc1:v2:`.
5. Quando não houver mais `v1` (backfill reescreve com a chave ativa), remover `v1` do anel.

O backfill de cifra, na segunda execução, não troca o nonce de uma linha que
já está no índice certo. Não é re-cifra automática a cada deploy.

## 5. Rollback

Ordem obrigatória. Tirar a env primeiro deixa o ciphertext ilegível e a
ingest devolve erro ao abrir o campo.

1. Com a chave **ainda** no ambiente, rodar o backfill em modo decrypt
   (comando na seção 6). Ele devolve id em claro, `value` numérico e JSON
   sem `_enc`. A segunda execução não altera linha já aberta.
2. Conferir uma leitura sintética: `GET /api/v1/wearables/patient/{id}/latest`.
3. Só então remover `FIELD_ENCRYPTION_KEY` (e o anel) e fazer deploy.
4. As colunas `*_enc` da 005 podem ficar vazias. Não há `DROP COLUMN` neste PR.

## 6. Passos que o Leandro precisa aprovar

Nada disso roda neste PR.

1. **Revisar o diff** e o texto que vai para a ficha da loja (seção 7).
2. **Criar os segredos** no Secret Manager do projeto `healthtech-gcp-2026`
   (`FIELD_ENCRYPTION_KEY` e `FIELD_BLIND_INDEX_KEY`). Não commitar.
3. **Decidir se o KMS entra agora.** O código aceita. Criar a key ring é
   outra mudança, fora deste PR. Dá para ligar só com Secret Manager.
4. **Deploy da revisão** com as envs ainda vazias. O boot loga
   `Criptografia de campos: desligada`. A ingest segue igual. O `sslmode`
   de TCP remoto passa a `require` — o socket `/cloudsql/` do serviço atual
   não muda.
5. **Aplicar a 005 e o backfill** numa janela combinada, com backup do
   Cloud SQL antes:

```bash
# Conferir volume, sem gravar. Não cria coluna.
BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes \
FIELD_ENCRYPTION_KEY="$DEK" \
FIELD_BLIND_INDEX_KEY="$BIK" \
FIELD_ENCRYPTION_KEY_ID=v1 \
DATABASE_URL="$DATABASE_URL" \
python scripts/backfill_field_encryption.py --dry-run

# Colunas aditivas + reescrita idempotente. Exige o confirm acima.
BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes \
FIELD_ENCRYPTION_KEY="$DEK" \
FIELD_BLIND_INDEX_KEY="$BIK" \
FIELD_ENCRYPTION_KEY_ID=v1 \
DATABASE_URL="$DATABASE_URL" \
python scripts/backfill_field_encryption.py --apply-schema
```

6. **Ligar a env na revisão do Cloud Run** (`FIELD_ENCRYPTION_KEY`,
   `FIELD_ENCRYPTION_KEY_ID`, `FIELD_BLIND_INDEX_KEY`) e subir tráfego.
   Escritas novas já saem cifradas mesmo antes do backfill; o backfill
   cobre o histórico. Os dois podem conviver.
7. **Smoke sintético** (não usar paciente real): um `POST /api/v1/wearables/ingest`
   e o mesmo `client_reading_id` de novo (esperado `duplicate`). A resposta
   traz `patient_id` e o vital em claro. No SQL, `patient_id` começa com
   `bi1.` e `frame` contém `_enc`.
8. **Rollback**, se preciso, é o modo decrypt da seção 5 — ainda com a chave
   presente:

```bash
BACKFILL_FIELD_ENCRYPTION_CONFIRM=yes \
FIELD_ENCRYPTION_KEY="$DEK" \
FIELD_BLIND_INDEX_KEY="$BIK" \
DATABASE_URL="$DATABASE_URL" \
python scripts/backfill_field_encryption.py --decrypt
```

O script recusa rodar se `BACKFILL_FIELD_ENCRYPTION_CONFIRM` não for `yes`.
A migração `005` não está na lista que o boot aplica (`001`–`004`).

## 7. Texto utilizável na ficha das lojas

Fatos deste serviço, sem adjetivo de certificação:

- O tráfego do app até a API usa HTTPS. A resposta envia HSTS.
- A conexão da API com o Cloud SQL por IP usa TLS (`sslmode=require` ou
  mais forte). O caminho padrão do Cloud Run é o socket do conector.
- Com a chave de campo ligada, telemetria de wearable (valores vitais e
  identificadores de paciente e de aparelho no registro da leitura), nome,
  telefone e condições do cadastro ficam cifrados no Postgres com AES-256-GCM.
  A chave fica no Secret Manager, não no repositório.
- A API key do app não é gravada no banco.

Enquanto a env não estiver ligada e o backfill não tiver rodado, o banco
ainda tem o histórico em claro. A ficha não deve dizer que o acervo antigo
já está cifrado antes desses dois passos.

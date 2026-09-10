# CONTRATO CORE — Território do Paciente para autorização (P0)

**Status:** **CONFIRMED**  
**Data:** 2026-09-10  
**Autoridade:** Leandro França de Mello (`leanderdulac`) — owner/maintainer HealthTech Core  
**Consumidor:** Next2U Web Profissional (implementação IAM: Rafael / `rafaeldepaulafigo-web/next2u-web`)  
**Escopo:** semântica dos campos já presentes nos GETs de Patient — **sem endpoint novo**

---

## 1. Endpoints

- `GET /api/v1/patients`
- `GET /api/v1/patients/{patient_id}`

Campos territoriais no objeto Patient (já observados no contrato Web):

| Campo | Tipo |
| --- | --- |
| `municipality_id` | `string` ou `null` / ausente |
| `ubs_id` | `string` ou `null` / ausente |

---

## 2. Semântica oficial para autorização (CONFIRMED)

### 2.1 Ambos presentes e não-null

Quando **`municipality_id` e `ubs_id` estão ambos presentes e não-null** (strings não vazias após trim):

> Representam o **único território ativo atual** do paciente para fins de **autorização profissional**.

Consumidores (BFF Next2U) DEVEM usar esse par como território atual do paciente na interseção com assignments profissionais.

### 2.2 Qualquer um ausente ou null

Quando **qualquer um** dos dois estiver **ausente**, **`null`**, ou string vazia:

> O território está **indefinido para autorização**.

Consumidores DEVEM aplicar **fail-closed**: **negar** acesso profissional a esse paciente para decisões de authz (listagem autorizada, detalhe, wearables).  
O paciente **pode continuar cadastrado** no Core; cadastro ≠ autorização.

### 2.3 Cardinalidade

- No P0, o GET expõe no máximo **um** par territorial ativo (ou indefinido).
- Histórico de mudanças de UBS/município é responsabilidade de persistência futura; este contrato fixa só a **leitura do ativo atual** nos GETs acima.

---

## 3. Identificador da UBS (CONFIRMED)

> O `ubs_id` retornado pelo Core **é o mesmo identificador canônico** que o `health_unit_id` usado nos assignments profissionais da Next2U.

- Consumidores DEVEM tratar **`ubs_id` ≡ `health_unit_id`** por igualdade de string.
- **Não** é necessário mapa separado no P0.
- Assignments Next2U DEVEM gravar `health_unit_id` com o mesmo valor publicado em `ubs_id` pelo Core.

---

## 4. O que este contrato NÃO faz

- Não cria endpoint novo.
- Não define APIs de escrita/admin de território (podem existir depois; a semântica dos GETs permanece).
- Não autentica profissionais (isso é Identity/Next2U + IdP).
- Não autoriza por si só: o BFF ainda exige sessão + binding + assignment + interseção territorial.

---

## 5. Formato de resposta ao pedido formal Next2U

Para as perguntas do P0 IAM:

**1. Território**

```
CONFIRMED
```

**2. ubs_id vs health_unit_id**

```
CONFIRMED
```

Documento canônico: este arquivo em `docs/contracts/PATIENT_TERRITORY_AUTHZ_P0.md` no repositório HealthTech.

# Healthtech — instruções para o Grok

Este arquivo vale só para sessões abertas neste repositório. Leia os documentos citados antes de mudar alerta, ingestão, companion ou qualquer afirmação clínica. Os números abaixo são o retrato lido em 26/09/2026. Se o arquivo-fonte divergir, o arquivo-fonte vence.

## Produto

O produto é o caminho em `docs/CRITICAL_PATH.md`:

pulseira ou simulador BLE → companion Android → `POST /api/v1/wearables/ingest` na API secure → matriz de 158 regras → painel.

A matriz de regras é o que o piloto mostra. Cada alerta sai com `decision_support` e sem conduta obrigatória. A API secure, o escopo da chave, a trava por paciente e o CI `pytest -m critical` já cobrem esse caminho.

## Laboratório

TCN (6h/24h/72h), conformal, Language v1, hemodinâmica, BMO e o conselho multi-agente ficam em laboratório. Não entram na resposta do piloto, no app nem num texto de risco para o usuário. O marcador pytest deles é `research`.

O Language v1 (`data/models/language_v1/`) só busca teses. Não participa da decisão clínica.

## Regras do piloto

- Não trate o F1 do `alert_matrix_classifier.pkl` como validação clínica. O dataset é sintético, gerado pelas mesmas regras (`src/clinical_intelligence/alert_matrix_dataset.py`, 21.100 amostras). Sem o `.pkl`, as regras continuam valendo. No piloto, a resposta vem da regra.
- A pulseira física HBand ainda está pendente em `docs/HBAND_COMPANION_CHECKLIST.md`. Sessão com `ingest_source=ble_sim` não conta como piloto. Contam `ble_hband` (SDK Veepoo) e `ble_standard` (perfil Bluetooth de saúde de outro relógio). O painel separa HTTP, simulado e BLE físico.
- Não promova o TCN. O treino em `data/models/temporal_model_meta.json` marca F1 de 0,98 em 6h e 24h. A validação em `data/clinical_validation/latest_validation.json` (05/07/2026, fonte `datalake_labels`, 5 pacientes, 752 sequências) tem F1 médio 0,64, sensibilidade 0,69 e especificidade 0,61. Em 6h o valor preditivo positivo é 0,37. Só volte a expor horizonte preditivo com corte por paciente, em gente que não entrou no treino.
- Não mostre intervalo conformal enquanto `data/models/conformal_calibration.json` seguir degenerado: 188 sequências, `q_hat` 1,0 em 6h e 0,0 em 24h.
- Não acrescente modelo de linguagem, local ou por API, para redigir parecer clínico. Isso não muda a evidência.

## Auditor de segurança e LGPD

O bot está em `docs/auditor/BOT.md`. Gere o relatório com `python run_auditoria_lgpd.py`. O texto marca evidência e lacuna. Não chame o projeto de certificado, não invente controlador, encarregado ou contrato de nuvem, e não copie segredo, chave ou dado de paciente. A hipótese que o companion exige, o RIPD, o registro de operações, a retenção e o plano de incidente estão em `docs/privacidade/`.

## Antes de alterar o caminho crítico

Confira `docs/CRITICAL_PATH.md`, `docs/openapi/hband-wearable.yaml` e `docs/HBAND_COMPANION_CHECKLIST.md`. Rode `pytest -m critical` no que o ingest, o alerta ou o companion tocar.

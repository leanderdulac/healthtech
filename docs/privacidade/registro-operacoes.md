# Registro das operações de tratamento

Registro do art. 37 para o caminho companion → ingest → alerta → painel. Os fatos são os do repositório em 28/09/2026.

| Campo | O que está escrito |
|---|---|
| Controlador | Não nomeado neste repositório. O produto se apresenta como Next2U Saúde / Saúde Responsiva. |
| Operador | API secure e o provedor de nuvem. A região citada pelo ledger e pelo Cloud Run é `us-central1`. Não há contrato de operador no repositório. |
| Encarregado | Não nomeado. Ver `encarregado.md`. |
| Titulares | Pacientes do piloto. |
| Dados sensíveis | Frequência cardíaca, variabilidade quando o frame traz, SpO2, pressão, temperatura. |
| Dados pessoais | Identificador do paciente, identificador do dispositivo, origem do ingest. O IP fica na trilha de stdout, sem o identificador cru no caminho. |
| Finalidade | Monitorar o piloto e gerar alerta como apoio à decisão, sem conduta obrigatória. |
| Base do art. 11 | Consentimento específico e destacado (inciso I), exigido pelo companion antes do envio. Ver `base-legal.md`. |
| Base do art. 7 | O mesmo consentimento, inciso I, para o identificador. |
| Compartilhamento | API secure e a nuvem que a hospeda. O repositório não mostra venda nem outro destinatário. |
| Transferência internacional | A região em uso é `us-central1`. Mecanismo do art. 33: nenhum. Ver `transferencia-internacional.md`. |
| Retenção | A política de retenção está em `retencao.md`. |
| Decisão automatizada | Alerta da matriz de regras, com revisão possível pelo titular, sem conduta obrigatória. |
| Direitos | Eliminação administrativa da telemetria, da frota, da revisão de piloto e, se houver banco, do cadastro. Acesso, correção e portabilidade pelo próprio titular não têm fluxo. |

# Política de Privacidade do app next2u SAÚDE

**Versão 2.1, atualizada em 18 de novembro de 2026.**

Esta política explica quais dados pessoais o aplicativo **next2u SAÚDE** (também publicado como **Next2U Paciente**), nas versões para **Android** e **iPhone**, trata, para que, com quem compartilha e como você pode exercer seus direitos previstos na Lei Geral de Proteção de Dados (Lei nº 13.709/2018, "LGPD"). O identificador do aplicativo é `br.com.next2u.saude.paciente` no Android (nome do pacote) e no iOS (Bundle ID).

## 1. Quem somos

O next2u SAÚDE é desenvolvido pela **Next2U**, startup incubada pelo **Instituto Inosu Acertas**. A controladora dos dados tratados pelo aplicativo é:

- Razão social: INSTITUTO INOSUACERTAS (Instituto Inosu Acertas)
- CNPJ: 34.471.321/0001-96
- Encarregado de dados (DPO) e canal de privacidade: Leandro França de Mello, **leandro.mello@iainstituto.org.br**

O app é usado em um **programa piloto de monitoramento remoto** com as secretarias municipais de saúde dos municípios participantes. Quando a equipe de saúde do município usa as suas leituras para decidir sobre o seu cuidado, a secretaria municipal também atua como controladora desse uso, de acordo com as regras do Sistema Único de Saúde (SUS).

## 2. Para que serve o app

O app conecta o seu relógio inteligente (modelo Veepoo VE30) ao celular por Bluetooth, guarda as medições no aparelho e as envia à plataforma da Next2U. Assim, a equipe de saúde do seu município consegue acompanhar seus sinais vitais à distância e agir mais cedo quando algo muda.

O app **não** faz diagnóstico e **não** substitui consulta, exame ou atendimento de emergência. Em caso de emergência, ligue para o SAMU (192).

## 3. Dados que tratamos

### 3.1 Medições do relógio (dados de saúde)

O app lê do relógio, conforme o modelo e as configurações permitirem:

- frequência cardíaca e variabilidade da frequência cardíaca (VFC);
- pressão arterial (sistólica e diastólica);
- saturação de oxigênio no sangue (SpO₂);
- temperatura;
- passos, distância e calorias estimadas;
- sono (minutos de sono profundo, sono leve e acordado);
- outras medições que o relógio oferecer, como eletrocardiograma, estimativa de glicose, composição corporal, respiração, fadiga e estado emocional. Essas medições ficam apenas no seu celular e não são enviadas à plataforma.

Medições de saúde são **dados pessoais sensíveis** pela LGPD e recebem proteção reforçada.

### 3.2 Dados que você informa em "Meu perfil"

Nome completo, idade, gênero, altura, peso, meta de passos por dia, meta de água por dia, contato de emergência, observações e o **nome da pulseira** (por exemplo, "Pulseira de Maria").

O app também cria uma **identificação do paciente** (por exemplo, `PAT-MARIA-7F3A`), que liga as suas leituras ao seu cadastro no programa.

### 3.3 Registros de bem-estar

Registros de hidratação (copos de água) e de exercícios de respiração que você faz no app. Eles ficam apenas no seu celular.

### 3.4 Dados técnicos

- identificador e modelo do relógio (incluindo o endereço Bluetooth);
- modelo do celular, usado como nome da pulseira apenas quando você não informou nome nem nome da pulseira;
- data e hora de cada leitura, um código único por leitura (para evitar duplicidade) e o histórico de envios (enviado, pendente ou com erro).

### 3.5 O que o app **não** coleta

- **Localização:** o app **não** lê nem guarda a sua localização (GPS). No Android, o sistema exige a permissão de localização para que o app possa procurar o relógio por Bluetooth; essa permissão é usada só para isso. No iPhone, a permissão de localização só é pedida se o aparelho exigir para encontrar o relógio por Bluetooth. Em nenhum dos casos a localização é lida ou armazenada.
- Contatos, fotos, câmera, microfone, mensagens ou arquivos do aparelho.
- O app **não** tem publicidade, **não** usa ferramentas de análise de uso ou de publicidade e **não** vende dados.

## 4. Para que usamos os dados e com que base legal

| Finalidade | Dados | Base legal (LGPD) |
|---|---|---|
| Mostrar suas medições e históricos no app | Medições, perfil, registros de bem-estar | Execução do serviço que você pediu (art. 7º, V) e, para dados de saúde, tutela da saúde (art. 11, II, "f") |
| Enviar suas leituras à equipe de saúde do seu município para monitoramento remoto | Identificação do paciente, nome da pulseira, medições enviadas (item 6) e dados técnicos | Tutela da saúde, em procedimento feito por profissionais de saúde, serviços de saúde ou autoridade sanitária (art. 11, II, "f") e execução de políticas públicas pela administração municipal (art. 11, II, "b") |
| Avisar no seu celular quando a frequência cardíaca sai da faixa definida | Frequência cardíaca | Tutela da saúde (art. 11, II, "f") |
| Gerar o "Resumo com IA" | Ver item 7 | Seu consentimento (art. 11, I) |
| Manter o serviço seguro, evitar leituras duplicadas e corrigir falhas | Dados técnicos | Legítimo interesse (art. 7º, IX) e tutela da saúde |

Não usamos seus dados para publicidade, criação de perfil comercial ou decisões automatizadas sobre o seu atendimento. Quem decide sobre o seu cuidado é sempre a equipe de saúde.

## 5. Onde os dados ficam guardados no seu celular

No Android, as medições, o perfil e a fila de envio ficam em um banco de dados **criptografado** no próprio aparelho (SQLCipher). Esse banco **não** entra no backup automático do Android nem é copiado na transferência para um celular novo. No iPhone, as medições, o perfil e a fila de envio também ficam no próprio aparelho. Em ambos os sistemas, ao desinstalar o app, esses dados são apagados do aparelho.

## 6. O que é enviado à plataforma da Next2U

A cada leitura, o app envia pela internet, com criptografia (HTTPS):

- identificação do paciente, nome da pulseira, identificador e modelo do relógio;
- data e hora da leitura e o código único da leitura;
- frequência cardíaca, pressão arterial, SpO₂, temperatura, passos, calorias, distância e VFC, quando o relógio mediu cada uma;
- a indicação de que a leitura veio do sensor real.

O nome completo, a idade, o peso, o contato de emergência, as observações, o sono e as medições do item 3.1 que ficam só no celular **não** são enviados à plataforma. Se a leitura não puder ser enviada na hora, por exemplo sem internet, ela fica na fila criptografada do celular até o próximo envio.

## 7. Resumo com IA (Google Gemini)

O **Resumo com IA** usa o serviço **Google Gemini** (Google LLC) e **vem desligado por padrão**. Ele só é usado depois do seu consentimento explícito no aplicativo. **Nenhum dado é enviado** ao Google Gemini sem esse consentimento.

Quando você autoriza, o app pode enviar ao Gemini, a partir da tela inicial, um resumo da sua semana com:

- médias e totais dos seus últimos 7 dias (frequência cardíaca, VFC, pressão arterial, passos, calorias e sono);
- os dados do seu perfil: nome, idade, gênero, altura, peso e observações.

O resumo é só um apoio informativo e não é avaliação médica. Quando o serviço de IA não está disponível, o app mostra um resumo simples calculado no próprio celular, sem enviar nada. O Google trata esses dados como fornecedor, segundo os termos da API Gemini, e pode processá-los fora do Brasil (item 9).

**Base legal:** o seu consentimento (LGPD, art. 11, I). Você pode retirar esse consentimento a qualquer momento em **Ajustes**, desligando o Resumo com IA. Também pode pedir o desligamento por e-mail para **leandro.mello@iainstituto.org.br** com o assunto "Desligar Resumo com IA" e a identificação do paciente. Retirar o consentimento não afeta o monitoramento pela equipe de saúde.

## 8. Com quem compartilhamos

- **Equipe de saúde do seu município** (secretaria municipal de saúde e profissionais do programa piloto), que acompanha suas leituras.
- **Equipe técnica da Next2U**, apenas o necessário para operar e dar suporte à plataforma, com dever de sigilo.
- **Fornecedores de tecnologia**, que tratam os dados só por nossas instruções:
  - Google Cloud (Google LLC): hospedagem da plataforma e do banco de dados;
  - Google Gemini (Google LLC): Resumo com IA (item 7).
- **Autoridades**, quando houver obrigação legal ou ordem judicial.

- **Pessoas ou apps que você escolher:** o app permite exportar suas medições em planilha (CSV) ou compartilhar uma imagem do seu progresso. Isso só acontece quando você toca em compartilhar e escolhe o destino.

**Não vendemos, alugamos nem compartilhamos seus dados para publicidade.**

## 9. Transferência internacional

A plataforma da Next2U e o seu banco de dados ficam no Google Cloud, na região **us-central1 (Estados Unidos)**. O serviço Gemini também pode processar dados fora do Brasil. Essas transferências seguem o art. 33 da LGPD e se apoiam nas garantias contratuais dos fornecedores, que incluem criptografia e controle de acesso.

## 10. Por quanto tempo guardamos

- **No celular:** até você apagar os dados ou desinstalar o app. As leituras que já foram enviadas podem ser retiradas da fila de envio.
- **Na plataforma:** enquanto durar o seu acompanhamento no programa piloto. Depois disso, os dados são excluídos ou anonimizados em até 7 dias, exceto quando a lei ou a secretaria municipal de saúde exigir que sejam guardados por mais tempo, por exemplo como parte do registro de atendimento.
- **Cópias de segurança (backup) da plataforma:** são substituídas automaticamente e mantidas por até 7 dias.

## 11. Segurança

- A comunicação entre o app e a plataforma é criptografada (HTTPS), e o envio exige uma credencial de acesso.
- No Android, o banco de dados no aparelho é criptografado e fica fora do backup do sistema.
- O acesso à plataforma é restrito por usuário e perfil, e cada profissional vê só os pacientes do seu território.

Nenhum sistema é totalmente imune a incidentes. Se ocorrer um incidente que possa trazer risco ou dano relevante a você, vamos comunicar você e a Autoridade Nacional de Proteção de Dados (ANPD), como manda a LGPD.

## 12. Seus direitos

Pela LGPD (art. 18), você pode pedir a qualquer momento:

- confirmação de que tratamos seus dados e acesso a eles;
- correção de dados incompletos, inexatos ou desatualizados;
- anonimização, bloqueio ou eliminação de dados desnecessários ou tratados em desacordo com a lei;
- portabilidade;
- informação sobre com quem compartilhamos;
- revogação do consentimento (para o Resumo com IA) e eliminação dos dados tratados com base nele;
- revisão de decisões tomadas só por meios automatizados.

Você também pode reclamar à ANPD em www.gov.br/anpd.

Para pedir a exclusão dos seus dados, veja a seção "Como solicitar a exclusão dos seus dados" abaixo.

## 13. Como solicitar a exclusão dos seus dados {#exclusao}

**Dados no celular:** desinstale o app next2u SAÚDE. Isso apaga do aparelho todas as medições, o perfil, os registros de bem-estar e a fila de envio.

**Dados na plataforma da Next2U:**

1. Envie um e-mail para **leandro.mello@iainstituto.org.br** com o assunto **"Exclusão de dados"**.
2. Informe seu nome e a **identificação do paciente** que aparece em "Meu perfil" no app (por exemplo, `PAT-MARIA-7F3A`). Podemos pedir uma confirmação de identidade.
3. Em até **7 dias** após o pedido, excluímos:
   - as leituras do relógio enviadas à plataforma (frequência cardíaca, pressão arterial, SpO₂, temperatura, passos, calorias, distância e VFC);
   - os dados de perfil e de identificação ligados a você na plataforma (identificação do paciente, nome da pulseira e dados do relógio).
4. Confirmamos a exclusão por e-mail.

**O que pode ser mantido:** quando a lei exigir, por exemplo como parte do registro de atendimento guardado pela secretaria municipal de saúde, ou para cumprir obrigação legal ou ordem judicial, alguns dados podem ser mantidos pelo prazo legal. Nesse caso, vamos explicar quais dados e por quê. Cópias de segurança são substituídas automaticamente em até 7 dias.

Ao fim do seu acompanhamento no programa, os dados também são excluídos ou anonimizados em até 7 dias, com as mesmas exceções legais.

## 14. Crianças e adolescentes

O app é destinado **somente a pessoas com 18 anos ou mais**, participantes do programa piloto. Não coletamos dados de menores de idade de propósito. Se descobrirmos que coletamos, vamos excluí-los.

## 15. Permissões do aplicativo

### 15.1 Android

| Permissão | Para quê |
|---|---|
| Bluetooth (procurar e conectar dispositivos) | Encontrar e se comunicar com o relógio |
| Localização | Exigida pelo Android para a busca Bluetooth. A localização não é lida nem guardada |
| Notificações | Avisos de frequência cardíaca e status da conexão |
| Serviço em primeiro plano, iniciar com o celular, manter ativo, alarmes e ignorar otimização de bateria | Manter a conexão com o relógio e os envios funcionando em segundo plano |
| Internet e estado da rede | Enviar as leituras e, se você autorizar, o Resumo com IA |

### 15.2 iPhone (iOS)

| Permissão | Para quê |
|---|---|
| Bluetooth | Conectar o relógio e receber as medições, inclusive quando o app está em segundo plano |
| Localização | Só é pedida se o iPhone exigir para encontrar o relógio por Bluetooth. A localização não é lida nem guardada |
| Notificações | Avisos de frequência cardíaca e status da conexão |
| Internet | Enviar as leituras e, se você autorizar, o Resumo com IA |

O app **não** usa o HealthKit nem o app Saúde da Apple. As medições vêm do relógio Veepoo, por Bluetooth.

## 16. Mudanças nesta política

Podemos atualizar esta política quando o app ou o programa mudar. A versão em vigor fica sempre neste endereço, com a data de atualização no topo. Se houver mudança relevante, vamos avisar no app.

## 17. Contato

Dúvidas ou pedidos sobre privacidade: **leandro.mello@iainstituto.org.br** (Encarregado de dados: Leandro França de Mello).

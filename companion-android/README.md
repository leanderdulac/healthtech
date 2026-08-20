# 📱 HealthTech Companion Android — Smartwatch VE30 & HBand Platform

[![Android](https://img.shields.io/badge/Platform-Android%2012%2B%20%28API%2026--34%29-3DDC84.svg?logo=android&logoColor=white)](https://developer.android.com)
[![Kotlin](https://img.shields.io/badge/Language-Kotlin%201.9-7F52FF.svg?logo=kotlin&logoColor=white)](https://kotlinlang.org/)
[![BLE](https://img.shields.io/badge/Protocol-Bluetooth%20Low%20Energy%205.0-0082FC.svg?logo=bluetooth&logoColor=white)](https://www.bluetooth.com)
[![AI Engine](https://img.shields.io/badge/AI%20Ingestion-HealthTech%20Cloud%20Run-FF6F00.svg)](https://healthtech-responsive-5794833455.us-central1.run.app)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](../LICENSE)

Aplicativo Android Companion nativo de alta confiabilidade para coleta de telemetria multissensorial contínua a partir dos smartwatches **VE30** (baseados na plataforma Veepoo / HBand SDK) e transmissão em tempo real para o ecossistema de Inteligência Artificial **HealthTech**.

---

## 🌟 Principais Recursos e Destaques

- **🔗 Conexão BLE Serializada & Auto-Reconexão**: Máquina de estados determinística para pareamento (`connectDevice` $	o$ `confirmDevicePwd("0000")` $	o$ `syncPersonInfo`) com auto-reconexão inteligente via backoff exponencial.
- **❤️ Coleta Multimodal Contínua (24/7)**:
  - Frequência Cardíaca instantânea e dinâmica (BPM)
  - Oximetria de Pulso (SpO2 %)
  - Temperatura Cutânea e Corporal (°C)
  - Pressão Arterial Sistólica e Diastólica (PAS / PAD mmHg)
  - Variabilidade da Frequência Cardíaca (HRV / RMSSD ms)
  - Sinal Óptico PPG Verde a 25Hz para Denoising BMO/Wavelet
- **🛡️ Fila Offline Resiliente (Outbox Buffer)**: Buffer local em memória/disco que armazena pacotes biométricos durante oscilações de 4G/Wi-Fi e os despacha automaticamente quando a conexão é restabelecida.
- **⚡ Foreground Service Persistente (`Ve30TelemetryService`)**: Notificação contínua no Android (`connectedDevice`) imune ao encerramento de processos em background e Doze Mode.
- **🧠 Integração Bidirecional com a IA**: Recebe em tempo real estimativas de **Dados Fantasmas via Filtro de Kalman Unscented (UKF)**, alertas de anomalia e pareceres do **Conselho Clínico Multi-Agente (Dempster-Shafer)**.

---

## 📐 Arquitetura de Comunicação

```mermaid
sequenceDiagram
    autonumber
    participant Watch as Smartwatch VE30
    participant App as Companion Android
    participant Service as Foreground Service
    participant API as HealthTech AI Platform (Cloud Run)

    Watch->>App: Anúncio BLE (VE30 / HBand)
    App->>Watch: Conexão GATT + Notify Enable
    App->>Watch: confirmDevicePwd("0000")
    Watch-->>App: Suporte a Funções (SpO2, Temp, BP, HRV, PPG)
    App->>Watch: syncPersonInfo(Altura, Peso, Idade, Sexo)
    App->>Service: Inicia Ve30TelemetryService (24/7)
    
    loop Monitoramento Contínuo (2 a 3s)
        Watch->>App: Telemetria Multi-Sensor
        App->>App: Agregação & Filtro de Movimento (wear_status)
        App->>API: POST /api/v1/wearables/ingest
        API-->>App: Dados Fantasmas UKF + Diagnóstico Bayesiano CID-10
        App->>Service: Atualiza Notificação com Sinais Vitais
    end
```

---

## 📂 Estrutura do Projeto Android

```
companion-android/
├── settings.gradle.kts          # Configuração de repositórios e módulos
├── build.gradle.kts             # Gradle raiz
├── VE30_INTEGRATION_GUIDE.md    # Guia detalhado de protocolos e hardware
├── SPRINT_A.md                  # Especificações técnicas
├── gradle/wrapper/              # Gradle Wrapper 8.2
└── sprint-a/                    # Módulo principal da aplicação
    ├── build.gradle.kts         # Dependências AndroidX, Coroutines, Material
    └── src/main/
        ├── AndroidManifest.xml  # Permissões Bluetooth LE e Foreground Service
        ├── java/com/healthtech/companion/
        │   ├── ble/
        │   │   ├── HbandConnectionManager.kt   # Gerenciador de ciclo de vida BLE
        │   │   ├── HbandRealtimeCollector.kt   # Ativação dos sensores vitais
        │   │   ├── Ve30TelemetryAggregator.kt  # Fusão temporal e debounce
        │   │   └── HbandHistorySync.kt         # Sincronizador de flash OriginData3
        │   ├── net/
        │   │   ├── HealthtechApiClient.kt      # Cliente HTTP com Outbox Queue
        │   │   └── Dtos.kt                     # Modelos de telemetria e resposta da IA
        │   ├── service/
        │   │   └── Ve30TelemetryService.kt     # Foreground Service 24/7
        │   └── ui/
        │       └── MainActivity.kt             # Interface de visualização em tempo real
        └── res/
            ├── layout/activity_main.xml        # Layout com cards biométricos
            └── values/{colors,strings,themes}.xml
```

---

## 🚀 Como Abrir e Executar no Android Studio

1. **Abrir no Android Studio**:
   - Abra o **Android Studio**.
   - Selecione **File $	o$ Open...** e aponte para a pasta `companion-android/`.
2. **Sincronizar o Gradle**:
   - O Android Studio detectará os arquivos `settings.gradle.kts` e sincronizará as dependências automaticamente.
3. **Executar**:
   - Conecte seu dispositivo Android via USB (com Depuração USB ativada) ou inicie um Emulador com suporte a Bluetooth.
   - Pressione **Run $	o$ Run 'sprint-a'** (Shift + F10).
4. **Testar sem Relógio Físico (Modo Simulador)**:
   - O app conta com gerador de sinais estocásticos de alta fidelidade integrado para validar toda a esteira mesmo sem o dispositivo físico presente!
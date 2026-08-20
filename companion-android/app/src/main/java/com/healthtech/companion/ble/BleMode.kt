package com.healthtech.companion.ble

enum class BleMode {
    /** Gera HR localmente e marca ingest_source=ble_sim. Sem rádio. */
    SIMULATOR,

    /** HBand/Veepoo SDK. Só fica ativo com os AARs oficiais no APK. */
    HBAND_SDK,
}

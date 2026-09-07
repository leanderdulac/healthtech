package com.healthtech.companion.ble

data class ScannedDevice(
    val mac: String,
    val name: String,
    val rssi: Int,
    val wearableLikely: Boolean,
) {
    val label: String get() = if (name.isBlank() || name == "N/A") mac else name
}

fun wearableScore(name: String?): Int {
    val n = (name ?: "").lowercase()
    if (n.isBlank() || n == "n/a") return 0
    val keys = listOf(
        "hband", "veepoo", "vp", "band", "watch", "fit", "hr", "spo",
        "pulse", "smart", "id115", "id205", "y68", "m4", "m6",
    )
    return keys.count { n.contains(it) }
}

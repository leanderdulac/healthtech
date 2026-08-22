# Third-Party SDK Binaries

The `.aar` and `.jar` files in this directory are the official Veepoo/HBand
Android BLE SDK, vendored unmodified from:

https://github.com/HBandSDK/Android_Ble_SDK
(path: `android_sdk_source/Demo/VpBluetoothSDK/app/libs/`)

Licensed under the Apache License, Version 2.0:
https://github.com/HBandSDK/Android_Ble_SDK/blob/master/LICENSE

| File | Purpose |
|---|---|
| `vpprotocol-2.3.80.15.aar` | Core Veepoo protocol SDK (`VPOperateManager`, listeners, data models) |
| `vpbluetooth-1.20.aar` | BLE transport layer (`com.inuker.bluetooth.library`) required by vpprotocol |
| `abpartool-release.aar` | Blood-pressure/algorithm parameter tool required by vpprotocol |
| `JL_Watch_V1.13.1_11214-release.aar` | Jieli chip support, required internally by `VPOperateManager` |
| `jl_rcsp_V0.7.2_527-release.aar` | Jieli RCSP protocol, required internally by `VPOperateManager` |
| `jl_bt_ota_V1.10.0_10931-release.aar` | Jieli BT OTA support, required internally by `VPOperateManager` |
| `BmpConvert_V1.6.0_10604-release.aar` | Jieli bitmap conversion utility, required internally by `VPOperateManager` |
| `gson-2.2.4.jar` | Gson version pinned by the vendor's own build (see their `build.gradle`) |

No changes were made to these binaries. See `companion-android/VE30_INTEGRATION_GUIDE.md`
for how they're wired into the app.

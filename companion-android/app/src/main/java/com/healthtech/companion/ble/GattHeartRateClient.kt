package com.healthtech.companion.ble

import android.annotation.SuppressLint
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import java.util.UUID

/**
 * Fallback SIG: Heart Rate Service 0x180D.
 *
 * HBand/Veepoo em geral **não** expõe 0x180D (protocolo proprietário).
 * Serve para pulseiras genéricas que o scan também lista.
 */
@SuppressLint("MissingPermission")
class GattHeartRateClient(
    context: Context,
    private val onStatus: (String) -> Unit,
    private val onBpm: (Int, String) -> Unit,
    private val onDisconnected: (String) -> Unit,
) {
    private val appContext = context.applicationContext
    private val handler = Handler(Looper.getMainLooper())
    private var gatt: BluetoothGatt? = null
    private var mac: String? = null

    fun connect(address: String) {
        close()
        mac = address
        val mgr = appContext.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
        val device = mgr.adapter?.getRemoteDevice(address)
        if (device == null) {
            onStatus("Adapter Bluetooth indisponível.")
            return
        }
        onStatus("GATT SIG: conectando $address…")
        gatt = if (Build.VERSION.SDK_INT >= 23) {
            device.connectGatt(appContext, false, callback, BluetoothDevice.TRANSPORT_LE)
        } else {
            @Suppress("DEPRECATION")
            device.connectGatt(appContext, false, callback)
        }
    }

    fun close() {
        runCatching { gatt?.disconnect() }
        runCatching { gatt?.close() }
        gatt = null
    }

    private val callback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                handler.post { onStatus("GATT conectado. Descobrindo serviços…") }
                g.requestMtu(247)
                g.discoverServices()
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                handler.post { onDisconnected(mac.orEmpty()) }
            }
        }

        override fun onMtuChanged(g: BluetoothGatt, mtu: Int, status: Int) {
            Log.i(TAG, "MTU=$mtu status=$status")
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            val hr = g.getService(HR_SERVICE)?.getCharacteristic(HR_MEASUREMENT)
            if (hr == null) {
                handler.post {
                    onStatus(
                        "Sem serviço Heart Rate (0x180D). " +
                            "Se for HBand, use o handshake Veepoo — não o GATT genérico.",
                    )
                }
                return
            }
            g.setCharacteristicNotification(hr, true)
            val cccd = hr.getDescriptor(CCCD)
            if (cccd != null) {
                @Suppress("DEPRECATION")
                cccd.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                g.writeDescriptor(cccd)
                handler.post { onStatus("Inscrito em 0x2A37. Aguardando notificações de FC…") }
            } else {
                handler.post { onStatus("CCCD ausente — leitura SIG incompleta.") }
            }
        }

        @Deprecated("Deprecated in Java")
        override fun onCharacteristicChanged(
            g: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
        ) {
            if (characteristic.uuid != HR_MEASUREMENT) return
            @Suppress("DEPRECATION")
            val bpm = HeartRateMeasurementParser.parseBpm(characteristic.value)
            if (bpm != null) {
                handler.post { onBpm(bpm, mac.orEmpty()) }
            }
        }
    }

    companion object {
        private const val TAG = "GattHr"
        private val HR_SERVICE: UUID = UUID.fromString("0000180d-0000-1000-8000-00805f9b34fb")
        private val HR_MEASUREMENT: UUID = UUID.fromString("00002a37-0000-1000-8000-00805f9b34fb")
        private val CCCD: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
    }
}

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
import java.util.ArrayDeque
import java.util.UUID

/**
 * Relógio que publica os perfis Bluetooth SIG de saúde.
 *
 * Heart Rate 0x180D, Pulse Oximeter 0x1822, Blood Pressure 0x1810,
 * Health Thermometer 0x1809. HBand/Veepoo em geral não publica esses
 * serviços — esse caminho fica em [HbandProtocolClient].
 */
@SuppressLint("MissingPermission")
class StandardWatchClient(
    context: Context,
    private val listener: Listener,
) {
    interface Listener {
        fun onStatus(message: String)
        fun onReady(mac: String, profiles: List<String>)
        fun onHeartRate(bpm: Int, mac: String)
        fun onSpo2(percent: Int, mac: String)
        fun onBloodPressure(systolic: Int, diastolic: Int, mac: String)
        fun onTemperature(celsius: Double, mac: String)
        fun onNoHealthProfile(mac: String)
        fun onDisconnected(mac: String)
    }

    private val appContext = context.applicationContext
    private val handler = Handler(Looper.getMainLooper())
    private val pending = ArrayDeque<BluetoothGattCharacteristic>()
    private val profiles = mutableListOf<String>()
    private var gatt: BluetoothGatt? = null
    private var mac: String? = null
    private var generation = 0

    fun connect(address: String) {
        generation += 1
        releaseGatt()
        mac = address
        profiles.clear()
        pending.clear()
        val mgr = appContext.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
        val device = mgr.adapter?.getRemoteDevice(address)
        if (device == null) {
            listener.onStatus("Adapter Bluetooth indisponível.")
            return
        }
        listener.onStatus("Perfil padrão: conectando $address…")
        gatt = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            device.connectGatt(appContext, false, callback, BluetoothDevice.TRANSPORT_LE)
        } else {
            @Suppress("DEPRECATION")
            device.connectGatt(appContext, false, callback)
        }
    }

    fun close() {
        generation += 1
        releaseGatt()
    }

    private fun releaseGatt() {
        val old = gatt
        gatt = null
        pending.clear()
        if (old != null) {
            runCatching { old.disconnect() }
            runCatching { old.close() }
        }
    }

    private fun sameSession(g: BluetoothGatt) = g == gatt

    private fun subscribeNext(g: BluetoothGatt) {
        if (!sameSession(g)) return
        val characteristic = pending.pollFirst()
        if (characteristic == null) {
            val names = profiles.toList()
            val address = mac.orEmpty()
            handler.post {
                if (!sameSession(g)) return@post
                listener.onReady(address, names)
                listener.onStatus("Inscrito em ${names.joinToString()}. Aguardando o relógio…")
            }
            return
        }
        g.setCharacteristicNotification(characteristic, true)
        val cccd = characteristic.getDescriptor(CCCD)
        if (cccd == null) {
            subscribeNext(g)
            return
        }
        val indicate = characteristic.properties and BluetoothGattCharacteristic.PROPERTY_INDICATE != 0
        val enable = if (indicate) {
            BluetoothGattDescriptor.ENABLE_INDICATION_VALUE
        } else {
            BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
        }
        val queued = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            g.writeDescriptor(cccd, enable) == BluetoothGatt.GATT_SUCCESS
        } else {
            @Suppress("DEPRECATION")
            cccd.value = enable
            @Suppress("DEPRECATION")
            g.writeDescriptor(cccd)
        }
        if (!queued) subscribeNext(g)
    }

    private fun enqueue(g: BluetoothGatt, service: UUID, characteristic: UUID, label: String) {
        val found = g.getService(service)?.getCharacteristic(characteristic) ?: return
        profiles += label
        pending.add(found)
    }

    private fun enqueueSpo2(g: BluetoothGatt) {
        val service = g.getService(PLX_SERVICE) ?: return
        val chosen = service.getCharacteristic(PLX_CONTINUOUS)
            ?: service.getCharacteristic(PLX_SPOT)
            ?: return
        profiles += "SpO2"
        pending.add(chosen)
    }

    private fun onBytes(uuid: UUID, value: ByteArray?) {
        val gen = generation
        val address = mac.orEmpty()
        fun deliver(block: () -> Unit) {
            handler.post {
                if (gen != generation) return@post
                block()
            }
        }
        when (uuid) {
            HR_MEASUREMENT -> SigMeasurementParser.heartRateBpm(value)?.let { bpm ->
                deliver { listener.onHeartRate(bpm, address) }
            }
            PLX_SPOT, PLX_CONTINUOUS -> SigMeasurementParser.pulseOximeterPercent(value)?.let { spo2 ->
                deliver { listener.onSpo2(spo2, address) }
            }
            BP_MEASUREMENT -> SigMeasurementParser.bloodPressureMmhg(value)?.let { (sys, dia) ->
                deliver { listener.onBloodPressure(sys, dia, address) }
            }
            TEMP_MEASUREMENT -> SigMeasurementParser.temperatureCelsius(value)?.let { celsius ->
                deliver { listener.onTemperature(celsius, address) }
            }
        }
    }

    private val callback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (!sameSession(g)) return
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                if (status != BluetoothGatt.GATT_SUCCESS) {
                    g.disconnect()
                    return
                }
                handler.post {
                    if (!sameSession(g)) return@post
                    listener.onStatus("GATT conectado. Procurando perfis de saúde…")
                }
                g.requestMtu(247)
                g.discoverServices()
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                val address = mac.orEmpty()
                handler.post {
                    if (!sameSession(g)) return@post
                    listener.onDisconnected(address)
                }
            }
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            if (!sameSession(g)) return
            if (status != BluetoothGatt.GATT_SUCCESS) {
                handler.post {
                    if (!sameSession(g)) return@post
                    listener.onStatus("Falha ao ler os serviços BLE ($status).")
                }
                return
            }
            profiles.clear()
            pending.clear()
            enqueue(g, HR_SERVICE, HR_MEASUREMENT, "FC")
            enqueueSpo2(g)
            enqueue(g, BP_SERVICE, BP_MEASUREMENT, "pressão")
            enqueue(g, TEMP_SERVICE, TEMP_MEASUREMENT, "temperatura")
            if (pending.isEmpty()) {
                val address = mac.orEmpty()
                handler.post {
                    if (!sameSession(g)) return@post
                    listener.onNoHealthProfile(address)
                }
                return
            }
            subscribeNext(g)
        }

        override fun onDescriptorWrite(
            g: BluetoothGatt,
            descriptor: BluetoothGattDescriptor,
            status: Int,
        ) {
            if (!sameSession(g)) return
            subscribeNext(g)
        }

        override fun onCharacteristicChanged(
            g: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray,
        ) {
            if (!sameSession(g)) return
            onBytes(characteristic.uuid, value)
        }

        @Deprecated("Deprecated in Java")
        override fun onCharacteristicChanged(
            g: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
        ) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) return
            if (!sameSession(g)) return
            @Suppress("DEPRECATION")
            onBytes(characteristic.uuid, characteristic.value)
        }
    }

    companion object {
        private val HR_SERVICE: UUID = UUID.fromString("0000180d-0000-1000-8000-00805f9b34fb")
        private val HR_MEASUREMENT: UUID = UUID.fromString("00002a37-0000-1000-8000-00805f9b34fb")
        private val PLX_SERVICE: UUID = UUID.fromString("00001822-0000-1000-8000-00805f9b34fb")
        private val PLX_SPOT: UUID = UUID.fromString("00002a5e-0000-1000-8000-00805f9b34fb")
        private val PLX_CONTINUOUS: UUID = UUID.fromString("00002a5f-0000-1000-8000-00805f9b34fb")
        private val BP_SERVICE: UUID = UUID.fromString("00001810-0000-1000-8000-00805f9b34fb")
        private val BP_MEASUREMENT: UUID = UUID.fromString("00002a35-0000-1000-8000-00805f9b34fb")
        private val TEMP_SERVICE: UUID = UUID.fromString("00001809-0000-1000-8000-00805f9b34fb")
        private val TEMP_MEASUREMENT: UUID = UUID.fromString("00002a1c-0000-1000-8000-00805f9b34fb")
        private val CCCD: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
    }
}

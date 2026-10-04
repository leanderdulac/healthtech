package com.healthtech.companion

import android.app.Application
import android.util.Log
import com.healthtech.companion.ble.CompanionSession
import com.veepoo.protocol.VPOperateManager

class HealthtechApp : Application() {
    lateinit var session: CompanionSession
        private set

    override fun onCreate() {
        super.onCreate()
        runCatching {
            VPOperateManager.getInstance().init(applicationContext)
        }.onFailure {
            Log.w("HealthtechApp", "VPOperateManager.init: ${it.message}")
        }
        session = CompanionSession(this)
    }
}

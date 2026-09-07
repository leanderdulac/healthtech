package com.healthtech.companion

import android.app.Application
import android.util.Log
import com.veepoo.protocol.VPOperateManager

class HealthtechApp : Application() {
    override fun onCreate() {
        super.onCreate()
        runCatching {
            VPOperateManager.getInstance().init(applicationContext)
        }.onFailure {
            Log.w("HealthtechApp", "VPOperateManager.init: ${it.message}")
        }
    }
}

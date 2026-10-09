package com.healthtech.companion.net.outbox

import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import java.io.File

/**
 * Fila offline em arquivo. Fecha o app e a fila continua no próximo processo.
 * Itens já enviados saem do arquivo.
 */
class FileOutboxStore(
    private val file: File,
) {
    private val gson = Gson()
    fun load(): MutableList<OutboxItem> {
        if (!file.exists() || file.length() == 0L) return mutableListOf()
        return runCatching {
            val type = object : TypeToken<MutableList<OutboxItem>>() {}.type
            gson.fromJson<MutableList<OutboxItem>>(file.readText(), type)
                ?.filterNotNull()
                ?.toMutableList()
                ?: mutableListOf()
        }.getOrDefault(mutableListOf())
    }

    fun save(items: MutableList<OutboxItem>) {
        items.removeAll { it.status == OutboxStatus.SENT }
        val dir = file.absoluteFile.parentFile ?: return
        if (!dir.exists()) {
            dir.mkdirs()
        }
        val tmp = File(dir, "${file.name}.tmp")
        tmp.writeText(gson.toJson(items))
        if (!tmp.renameTo(file)) {
            file.writeText(tmp.readText())
            tmp.delete()
        }
    }
}

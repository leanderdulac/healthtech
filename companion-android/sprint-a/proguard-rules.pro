# O SDK oficial Veepoo/HBand é carregado via reflection (ver HbandConnectionManager.initSdk).
# Sem essa regra, o R8 pode remover ou renomear as classes/métodos usados por Class.forName().
-keep class com.veepoo.protocol.** { *; }
-keep class com.inuker.bluetooth.** { *; }

-keepattributes Signature, InnerClasses, *Annotation*

# Modelos serializados manualmente via org.json (Dtos.kt) não usam reflection,
# mas mantemos os nomes de campo para facilitar depuração de payloads em produção.
-keepclassmembers class com.healthtech.companion.net.** {
    <fields>;
}

import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val localProperties = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) FileInputStream(file).use { load(it) }
}

fun secretProperty(name: String, default: String = ""): String =
    System.getenv(name) ?: localProperties.getProperty(name) ?: default

android {
    namespace = "com.healthtech.companion"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.healthtech.companion"
        minSdk = 26
        targetSdk = 34
        versionCode = 310
        versionName = "3.1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        buildConfigField("String", "HEALTHTECH_BASE_URL", "\"${secretProperty("HEALTHTECH_BASE_URL", "https://healthtech-responsive-5794833455.us-central1.run.app")}\"")
        buildConfigField("String", "HEALTHTECH_PATIENT_ID", "\"${secretProperty("HEALTHTECH_PATIENT_ID", "PAT-VE30-001")}\"")
        buildConfigField("String", "HEALTHTECH_INGEST_API_KEY", "\"${secretProperty("HEALTHTECH_INGEST_API_KEY")}\"")
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
        debug {
            applicationIdSuffix = ".debug"
            isDebuggable = true
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        buildConfig = true
        viewBinding = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.11.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("androidx.cardview:cardview:1.0.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")

    // SDK Veepoo / HBand AARs (quando disponíveis em libs/)
    implementation(fileTree("libs") { include("*.aar", "*.jar") })

    // McuMgr (Nordic) é exigido internamente pelo VPOperateManager para o fluxo de OTA
    // (McuMgrOtaManager.init é chamado em todo onConnectStatusChanged). Sem esta dependência
    // o app crasha com NoClassDefFoundError assim que o BLE conecta a um relógio real.
    implementation("no.nordicsemi.android:mcumgr-core:2.7.4")
    implementation("no.nordicsemi.android:mcumgr-ble:2.7.4")
    implementation("no.nordicsemi.android.support.v18:scanner:1.4.2")
    implementation("androidx.localbroadcastmanager:localbroadcastmanager:1.1.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20231013")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
}
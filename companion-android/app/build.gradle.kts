import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

fun prop(key: String, default: String = ""): String =
    (localProps.getProperty(key) ?: default).replace("\"", "\\\"")

android {
    namespace = "com.healthtech.companion"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.healthtech.companion"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0-mvp"

        // Default de debug = emulador → host. Produção: local.properties.
        buildConfigField(
            "String",
            "DEFAULT_BASE_URL",
            "\"${prop("HEALTHTECH_BASE_URL", "http://10.0.2.2:8080")}\"",
        )
        buildConfigField(
            "String",
            "DEFAULT_INGEST_API_KEY",
            "\"${prop("HEALTHTECH_INGEST_API_KEY", "")}\"",
        )
        buildConfigField(
            "String",
            "DEFAULT_PATIENT_ID",
            "\"${prop("HEALTHTECH_PATIENT_ID", "PAT-HBAND-001")}\"",
        )
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
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
        compose = true
        buildConfig = true
    }
    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.14"
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.06.00")
    implementation(composeBom)
    androidTestImplementation(composeBom)

    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    debugImplementation("androidx.compose.ui:ui-tooling")

    implementation(project(":client"))
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
}

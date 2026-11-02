plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "es.vibi.movil"
    compileSdk = 35

    defaultConfig {
        applicationId = "es.vibi.movil"
        minSdk = 31
        targetSdk = 35
        versionCode = 1
        versionName = "0.1-prueba"
        ndk { abiFilters += "arm64-v8a" }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("io.getstream:stream-webrtc-android:1.3.8")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    implementation("com.alphacephei:vosk-android:0.3.47")
    implementation("net.java.dev.jna:jna:5.13.0@aar")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
}

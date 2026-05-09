import java.util.Properties

val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.zero.wearablebridge"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.zero.wearablebridge"
        minSdk = 29 // Android 10 — DAT SDK baseline
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        // Meta DAT credentials. Use "0" for Developer Mode (attestation
        // skipped) or paste the real values from the Wearables Developer
        // Center into local.properties:
        //   meta.application.id=...
        //   meta.client.token=...
        val metaAppId = localProps.getProperty("meta.application.id") ?: "0"
        val metaClientToken = localProps.getProperty("meta.client.token") ?: ""
        manifestPlaceholders["metaApplicationId"] = metaAppId
        manifestPlaceholders["metaClientToken"] = metaClientToken
    }

    buildFeatures {
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.lifecycle.service)
    implementation(libs.material)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.okhttp)

    implementation(libs.camerax.core)
    implementation(libs.camerax.camera2)
    implementation(libs.camerax.lifecycle)

    // Meta Wearables Device Access Toolkit — pulled from GitHub Packages.
    // See settings.gradle.kts for the maven repo + auth.
    implementation(libs.mwdat.core)
    implementation(libs.mwdat.camera)
    implementation(libs.mwdat.mockdevice)
}

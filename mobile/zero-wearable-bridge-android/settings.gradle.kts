pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

import java.util.Properties

val localProperties = Properties().apply {
    val f = file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()

        // Meta DAT SDK — GitHub Packages. Requires a personal access token
        // with at least `read:packages` scope, provided via one of:
        //   1. GITHUB_TOKEN environment variable
        //   2. `github_token=...` in local.properties
        maven {
            url = uri("https://maven.pkg.github.com/facebook/meta-wearables-dat-android")
            credentials {
                username = ""
                password = System.getenv("GITHUB_TOKEN")
                    ?: localProperties.getProperty("github_token")
                    ?: ""
            }
        }
    }
}

rootProject.name = "zero-wearable-bridge"
include(":app")

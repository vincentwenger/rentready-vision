plugins {
    alias(libs.plugins.android.application)
}

android {
    namespace = "com.rentreadyvision.tv"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "com.rentreadyvision.tv"
        minSdk = 28
        targetSdk = 37
        versionCode = 3
        versionName = "1.0.2"

    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.leanback)
    implementation(libs.glide)
}
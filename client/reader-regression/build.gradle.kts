plugins { kotlin("multiplatform") version "2.3.20" }

// Compile the actual modified sources, without the unrelated Android/UI dependency graph.
val data = file("../legado-source/data/src")
kotlin {
    jvm()
    jvmToolchain(21)
    sourceSets {
        commonMain {
            kotlin.srcDir(data.resolve("commonMain/kotlin"))
            kotlin.include("**/RemoteZipCore.kt", "**/RangedSource.kt", "**/ZipStructure.kt", "**/Inflate.kt", "**/ZipIOException.kt", "**/EpubChapterPosition.kt")
            dependencies { implementation("org.jetbrains.kotlinx:kotlinx-serialization-core:1.11.0") }
        }
        jvmMain {
            kotlin.srcDir(data.resolve("jvmAndAndroidMain/kotlin"))
            kotlin.include("**/RemoteEpubSnapshot.kt", "**/Inflate.jvmAndAndroid.kt", "**/ZipIOException.jvmAndAndroid.kt")
            dependencies { implementation("com.squareup.okhttp3:okhttp:5.4.0") }
        }
        jvmTest {
            kotlin.srcDir(data.resolve("jvmAndAndroidTest/kotlin"))
            kotlin.include("**/RemoteZipCoreTest.kt", "**/RemoteEpubSnapshotTest.kt", "**/ZipTestFixtures.kt", "**/EpubChapterPositionTest.kt")
            dependencies { implementation("junit:junit:4.13.2") }
        }
    }
}

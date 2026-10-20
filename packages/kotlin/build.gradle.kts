plugins {
    kotlin("multiplatform") version "2.4.0"
    kotlin("plugin.serialization") version "2.4.0"
    id("org.openapi.generator") version "7.25.0"
}

group = "dev.pydantic"
version = "0.1.0"

val ktorVersion = "3.5.1"
val generatedClient = layout.buildDirectory.dir("generated/openapi")
val generatedVersion = layout.buildDirectory.dir("generated/version")

repositories {
    mavenCentral()
}

openApiGenerate {
    generatorName.set("kotlin")
    library.set("multiplatform")
    inputSpec.set(layout.projectDirectory.file("openapi.json").asFile.path)
    outputDir.set(generatedClient.get().asFile.path)
    packageName.set("dev.pydantic.genaiprices")
    configOptions.set(mapOf("dateLibrary" to "kotlinx-datetime"))
    // kotlinx.serialization cannot serialize `Any`, so free-form JSON stays a `JsonElement`.
    typeMappings.set(mapOf("AnyType" to "JsonElement"))
    importMappings.set(mapOf("JsonElement" to "kotlinx.serialization.json.JsonElement"))
    generateApiTests.set(false)
    generateModelTests.set(false)
    generateApiDocumentation.set(false)
    generateModelDocumentation.set(false)
}

val generateVersion by tasks.registering {
    val version = project.version.toString()
    val output = generatedVersion
    inputs.property("version", version)
    outputs.dir(output)
    doLast {
        val file = output.get().file("dev/pydantic/genaiprices/Version.kt").asFile
        file.parentFile.mkdirs()
        file.writeText("package dev.pydantic.genaiprices\n\ninternal const val VERSION = \"$version\"\n")
    }
}

kotlin {
    jvm()
    iosArm64()
    iosSimulatorArm64()
    iosX64()

    sourceSets {
        commonMain {
            kotlin.srcDir(generatedClient.map { it.dir("src/commonMain/kotlin") })
            kotlin.srcDir(generatedVersion)
            dependencies {
                api("io.ktor:ktor-client-core:$ktorVersion")
                implementation("io.ktor:ktor-client-content-negotiation:$ktorVersion")
                implementation("io.ktor:ktor-serialization-kotlinx-json:$ktorVersion")
                api("org.jetbrains.kotlinx:kotlinx-datetime:0.8.0")
            }
        }
        commonTest {
            dependencies {
                implementation(kotlin("test"))
                implementation("io.ktor:ktor-client-mock:$ktorVersion")
                implementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.11.0")
            }
        }
        jvmMain {
            dependencies {
                implementation("io.ktor:ktor-client-cio:$ktorVersion")
            }
        }
        iosMain {
            dependencies {
                implementation("io.ktor:ktor-client-darwin:$ktorVersion")
            }
        }
    }
}

tasks.matching { it.name.startsWith("compileKotlin") || it.name.endsWith("SourcesJar") }.configureEach {
    dependsOn(tasks.openApiGenerate, generateVersion)
}

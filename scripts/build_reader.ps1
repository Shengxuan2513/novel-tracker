param([ValidateSet('test','apk')][string]$Mode = 'test', [string]$BuildRoot = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not $BuildRoot) {
    $digest = [System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($projectRoot))
    $suffix = ([BitConverter]::ToString($digest)).Replace('-', '').Substring(0, 12)
    $BuildRoot = Join-Path $env:PUBLIC "novel-reader-$suffix"
}
$buildRoot = $BuildRoot
if ($buildRoot -match '[^\x00-\x7F]') { throw 'BuildRoot must use an ASCII path; specify -BuildRoot.' }
if (-not (Test-Path -LiteralPath $buildRoot)) {
    New-Item -ItemType Junction -Path $buildRoot -Target $projectRoot | Out-Null
}
if ((Get-Item -LiteralPath $buildRoot).Target -ne $projectRoot) {
    throw "Build alias belongs to another directory: $buildRoot"
}
$toolRoot = Join-Path $buildRoot 'storage\reader-toolchain'
$env:JAVA_HOME = (Get-ChildItem -LiteralPath (Join-Path $toolRoot 'jdk21') -Directory | Select-Object -First 1).FullName
$java17 = (Get-ChildItem -LiteralPath (Join-Path $toolRoot 'jdk17') -Directory | Select-Object -First 1).FullName
$env:ANDROID_HOME = Join-Path $toolRoot 'android-sdk'
$env:GRADLE_USER_HOME = Join-Path $toolRoot 'gradle-cache'
$gradle = Join-Path $toolRoot 'gradle\gradle-9.6.0\bin\gradle.bat'
$source = Join-Path $buildRoot 'client\legado-source'
$arguments = @('--no-daemon', '--console=plain', '-Dorg.gradle.jvmargs=-Xmx4g -Dfile.encoding=UTF-8',
    '-Pandroid.overridePathCheck=true', "-Porg.gradle.java.installations.paths=$env:JAVA_HOME,$java17")
if ($Mode -eq 'test') {
    $source = Join-Path $buildRoot 'client\reader-regression'
    $arguments += @('jvmTest')
} else {
    $arguments += @(':app:assembleAppDebug', '-PappVersion=3.26.100113', '-PepubFixBuild=true')
}
Push-Location $source
try { & $gradle @arguments; if ($LASTEXITCODE -ne 0) { throw "Gradle failed: $LASTEXITCODE" } }
finally { Pop-Location }
if ($Mode -eq 'apk') {
    $apk = Get-ChildItem -LiteralPath (Join-Path $source 'app\build\outputs\apk') -Recurse -Filter '*.apk' |
        Where-Object { $_.Name -match 'arm64-v8a' -and $_.FullName -match 'debug' } | Select-Object -First 1
    if (-not $apk) { throw 'ARM64 debug APK not found' }
    Copy-Item -LiteralPath $apk.FullName -Destination (Join-Path $projectRoot 'client\legado-epubfix-arm64.apk')
}

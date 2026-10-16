param(
    [switch]$BuildOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$androidProject = Join-Path $root "fire-tv"

Write-Host "`n=== RENTREADY VISION - FIRE TV LAUNCHER ==="

# Find Java, preferring the Android Studio bundled JDK.
$javaCandidates = @(
    "$env:ProgramFiles\Android\Android Studio\jbr",
    "$env:ProgramFiles\Android\Android Studio\jre"
)

if ($env:JAVA_HOME) {
    $javaCandidates = @($env:JAVA_HOME) + $javaCandidates
}

$javaHome = $null

foreach ($candidate in $javaCandidates) {
    if (Test-Path (Join-Path $candidate "bin\java.exe")) {
        $javaHome = $candidate
        break
    }
}

if (-not $javaHome) {
    throw "Java not found. Install Android Studio with its bundled JDK."
}

$env:JAVA_HOME = $javaHome
$env:Path = "$javaHome\bin;$env:Path"

Write-Host "Java: $javaHome"

# Find Android SDK.
if (-not $env:ANDROID_HOME -or
    -not (Test-Path $env:ANDROID_HOME)) {

    $candidate = Join-Path $env:LOCALAPPDATA "Android\Sdk"

    if (-not (Test-Path $candidate)) {
        throw "Android SDK not found. Install it through Android Studio."
    }

    $env:ANDROID_HOME = $candidate
}

Write-Host "Android SDK: $env:ANDROID_HOME"

# Build APK using the checked-in Gradle wrapper.
$gradlew = Join-Path $androidProject "gradlew.bat"

if (-not (Test-Path $gradlew)) {
    throw "Gradle wrapper not found."
}

Write-Host "`nBuilding Fire TV APK..."

Push-Location $androidProject

try {
    & $gradlew :app:assembleDebug --no-daemon --console=plain

    if ($LASTEXITCODE -ne 0) {
        throw "Gradle build failed."
    }
}
finally {
    Pop-Location
}

$apk = Join-Path $androidProject `
    "app\build\outputs\apk\debug\app-debug.apk"

if (-not (Test-Path $apk)) {
    throw "APK missing after build."
}

if ((Get-Item $apk).Length -le 0) {
    throw "APK is empty."
}

Write-Host "Build: PASS"

if ($BuildOnly) {
    Write-Host "`n=== BUILD ONLY - SUCCESS ==="
    Write-Host "APK: $apk"
    return
}

# Locate and validate one running Android TV emulator.
$adb = Join-Path $env:ANDROID_HOME "platform-tools\adb.exe"

if (-not (Test-Path $adb)) {
    throw "ADB not found. Install Android SDK Platform-Tools."
}

$deviceOutput = @(& $adb devices -l)

if ($LASTEXITCODE -ne 0) {
    throw "ADB device check failed."
}

$devices = @($deviceOutput | Where-Object {
    $_ -match '^\S+\s+device(?:\s+.*)?$'
})

if ($devices.Count -ne 1) {
    throw "Start exactly one Android TV emulator."
}

$serial = ($devices[0] -split '\s+')[0]

if ($serial -notmatch '^emulator-\d+$') {
    throw "Physical or unsupported device detected. Installation blocked."
}

$features = @(& $adb -s $serial shell pm list features)

if ($LASTEXITCODE -ne 0 -or
    -not ($features -match 'feature:android.software.leanback(\s|$)')) {
    throw "Device does not advertise Android TV Leanback support."
}

$bootStatus = @(& $adb -s $serial shell getprop sys.boot_completed)

if ($LASTEXITCODE -ne 0 -or
    ($bootStatus -join "").Trim() -ne "1") {
    throw "Android TV emulator has not finished booting."
}

Write-Host "Android TV emulator: VERIFIED"
Write-Host "Device: $serial"
Write-Host "`nInstalling on device: $serial"

& $adb -s $serial install -r $apk

if ($LASTEXITCODE -ne 0) {
    throw "APK installation failed."
}

Write-Host "`nLaunching RentReady Vision..."

& $adb -s $serial shell am start `
    -n "com.rentreadyvision.tv/.MainActivity"

if ($LASTEXITCODE -ne 0) {
    throw "Application launch failed."
}

Write-Host "`n=== FIRE TV LAUNCHER - SUCCESS ==="
Write-Host "APK: BUILD VERIFIED"
Write-Host "Installation: PASS"
Write-Host "Launch command: PASS"
Write-Host "A valid inspection pairing is required for protected content."

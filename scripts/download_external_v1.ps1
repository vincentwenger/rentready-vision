param(
    [string]$Root = (Join-Path (Get-Location) "evaluation\external_v1"),
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# =============================================================================
# RentReady Vision - External Validation Dataset v1 Downloader
#
# PURPOSE:
#   Download a small set of externally sourced Wikimedia Commons videos
#   and record source/license metadata.
#
# IMPORTANT:
#   This script ONLY downloads and organizes source videos.
#
#   It DOES NOT:
#     - run RentReady Vision
#     - extract frames
#     - run defect detection
#     - train anything
#     - evaluate anything
#
# =============================================================================


# -----------------------------------------------------------------------------
# Wikimedia request configuration
# -----------------------------------------------------------------------------

$WikimediaHeaders = @{
    "User-Agent" = "RentReadyVisionExternalDataset/1.1 (https://github.com/vincentwenger/rentready-vision)"
    "Accept"     = "*/*"
}

# Delay between successful Wikimedia requests.
# This deliberately keeps the downloader conservative.
$RequestDelaySeconds = 5

# Number of times to retry a request if Wikimedia rate-limits us.
$MaxAttempts = 8


# -----------------------------------------------------------------------------
# Dataset definition
# -----------------------------------------------------------------------------

$clips = @(

    # =========================================================================
    # POSITIVE / DEFECT CLIPS
    # =========================================================================

    [pscustomobject]@{
        id = "ext001"
        split = "positive"
        class = "water_leak"
        label = "defect"
        role = "primary"
        localName = "ext001_water_leak_apartment.webm"
        commonsFile = "Water_Dripping_into_a_Bucket_in_a_Derelict_Apartment_in_Canada.webm"
        declaredLicense = "CC BY 4.0"
        description = "Active water leak dripping into a bucket inside a derelict apartment."
    },

    [pscustomobject]@{
        id = "ext002"
        split = "positive"
        class = "water_leak"
        label = "defect"
        role = "primary"
        localName = "ext002_water_leak_abandoned_house.webm"
        commonsFile = "Abandoned_house_-_water_leakage_-_2023-07-24.webm"
        declaredLicense = "CC BY-SA 4.0"
        description = "Water leakage inside an abandoned house."
    },

    [pscustomobject]@{
        id = "ext003"
        split = "positive"
        class = "dripping_faucet"
        label = "defect"
        role = "primary"
        localName = "ext003_dripping_faucet.webm"
        commonsFile = "Tropfender_Wasserhahn_20240827_C1004.webm"
        declaredLicense = "CC BY 4.0"
        description = "Subtle dripping faucet defect."
    },

    [pscustomobject]@{
        id = "ext004"
        split = "positive"
        class = "door_damage"
        label = "defect"
        role = "primary"
        localName = "ext004_door_glass_damage.webm"
        commonsFile = "Front_door_spyhole.webm"
        declaredLicense = "CC BY 3.0"
        description = "Front-door hardware/glass condition including visible cracking."
    },

    [pscustomobject]@{
        id = "ext005"
        split = "positive"
        class = "toilet_issue"
        label = "defect"
        role = "stress_test"
        localName = "ext005_toilet_unusable_edge_case.webm"
        commonsFile = "WC_unbenutzbar.webm"
        declaredLicense = "CC BY-SA 4.0"
        description = "Unusable toilet context. Non-residential edge case."
    },

    [pscustomobject]@{
        id = "ext006"
        split = "positive"
        class = "unfinished_surface"
        label = "defect"
        role = "primary"
        localName = "ext006_renovation_surface_04.webm"
        commonsFile = "Gouripur_House_-_Kalimpong_-_Interiors_-_04.webm"
        declaredLicense = "CC BY-SA 4.0"
        description = "House interior under renovation; useful unfinished/damaged surface footage."
    },

    [pscustomobject]@{
        id = "ext007"
        split = "positive"
        class = "unfinished_surface"
        label = "defect"
        role = "primary"
        localName = "ext007_renovation_surface_05.webm"
        commonsFile = "Gouripur_House_-_Kalimpong_-_Interiors_-_05.webm"
        declaredLicense = "CC BY-SA 4.0"
        description = "Renovated/unfinished house interior with walls, floors and property-condition context."
    },


    # =========================================================================
    # CLEAN / NEGATIVE CLIPS
    # =========================================================================

    [pscustomobject]@{
        id = "ext008"
        split = "clean"
        class = "walkthrough"
        label = "clean"
        role = "primary"
        localName = "ext008_clean_room_walkthrough.webm"
        commonsFile = "Porto_Santo_Maria_hotel_room_tour_in_Funchal,_Madeira.webm"
        declaredLicense = "CC BY 3.0"
        description = "Long clean room/interior walkthrough."
    },

    [pscustomobject]@{
        id = "ext009"
        split = "clean"
        class = "bathroom"
        label = "clean"
        role = "primary"
        localName = "ext009_clean_bathroom.webm"
        commonsFile = "Man_in_hotel_bathroom_with_mirrors_all_around,_turning_and_making_video_thereof.webm"
        declaredLicense = "CC BY-SA 4.0"
        description = "Bathroom walkthrough with mirrors and normal fixtures."
    },

    [pscustomobject]@{
        id = "ext010"
        split = "clean"
        class = "kitchen"
        label = "clean"
        role = "stress_test"
        localName = "ext010_clean_traditional_kitchen.webm"
        commonsFile = "Traditional_Ladakhi_kitchen_interior_at_Central_Asian_Museum,_Leh,_Ladakh,_India.webm"
        declaredLicense = "CC BY-SA 4.0"
        description = "Clean kitchen/interior with visual style unlike a typical US rental."
    },

    [pscustomobject]@{
        id = "ext011"
        split = "clean"
        class = "plumbing"
        label = "clean"
        role = "primary"
        localName = "ext011_normal_sensor_faucet.webm"
        commonsFile = "Sensor_faucet_in_a_hotel_room.webm"
        declaredLicense = "CC BY-SA 4.0"
        description = "Normally operating faucet."
    },

    [pscustomobject]@{
        id = "ext012"
        split = "clean"
        class = "toilet"
        label = "clean"
        role = "primary"
        localName = "ext012_normal_toilet_flush.webm"
        commonsFile = "The_toilet_starts_flushing_and_then_stops_making_a_sound.webm"
        declaredLicense = "CC0"
        description = "Normal toilet flushing/refilling."
    },

    [pscustomobject]@{
        id = "ext013"
        split = "clean"
        class = "plumbing"
        label = "clean"
        role = "primary"
        localName = "ext013_normal_water_taps.webm"
        commonsFile = "Video_of_water_flowing_from_taps.webm"
        declaredLicense = "CC BY-SA 4.0"
        description = "Normal water flow from taps."
    },

    [pscustomobject]@{
        id = "ext014"
        split = "clean"
        class = "plumbing"
        label = "clean"
        role = "primary"
        localName = "ext014_normal_running_tap.webm"
        commonsFile = "A_running_tap_of_water.webm"
        declaredLicense = "CC BY 4.0"
        description = "Normal running tap."
    },

    [pscustomobject]@{
        id = "ext015"
        split = "clean"
        class = "bathroom"
        label = "clean"
        role = "primary"
        localName = "ext015_normal_shower.webm"
        commonsFile = "Some_water_coming_out_of_a_shower.webm"
        declaredLicense = "CC BY-SA 4.0"
        description = "Normal shower water flow."
    },

    [pscustomobject]@{
        id = "ext016"
        split = "clean"
        class = "bathroom"
        label = "clean"
        role = "primary"
        localName = "ext016_normal_bathroom_fan.webm"
        commonsFile = "A_fan_in_the_shower_which_circulates_the_air_in_the_bathroom..webm"
        declaredLicense = "CC BY 3.0"
        description = "Normal bathroom ventilation hardware."
    },

    [pscustomobject]@{
        id = "ext017"
        split = "clean"
        class = "doors"
        label = "clean"
        role = "primary"
        localName = "ext017_normal_doors.webm"
        commonsFile = "Doors_at_Wilson_House,_London.webm"
        declaredLicense = "CC BY-SA 4.0"
        description = "Normal doors and door hardware."
    },

    [pscustomobject]@{
        id = "ext018"
        split = "clean"
        class = "toilet"
        label = "clean"
        role = "hard_negative"
        localName = "ext018_toilet_cleaning_activity.webm"
        commonsFile = "Cleaning_the_Toilet_(TESDA).webm"
        declaredLicense = "Public domain / government work"
        description = "Toilet cleaning activity with people/tools/motion."
    }
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

function Get-RetryAfterSeconds {

    param(
        $Exception,
        [int]$DefaultSeconds = 30
    )

    $delay = $DefaultSeconds

    try {
        if ($null -ne $Exception.Response) {

            $headers = $Exception.Response.Headers

            if ($null -ne $headers) {

                $retryAfter = $null

                try {
                    $retryAfter = $headers["Retry-After"]
                }
                catch {
                }

                if ($retryAfter) {

                    $parsed = 0

                    if ([int]::TryParse(
                        [string]$retryAfter,
                        [ref]$parsed
                    )) {
                        $delay = [Math]::Max($parsed, $DefaultSeconds)
                    }
                }
            }
        }
    }
    catch {
    }

    return $delay
}


function Invoke-WikimediaRestRequest {

    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {

        try {

            $response = Invoke-RestMethod `
                -Uri $Uri `
                -Headers $WikimediaHeaders `
                -Method Get

            Start-Sleep -Seconds $RequestDelaySeconds

            return $response
        }
        catch {

            if ($attempt -eq $MaxAttempts) {
                throw
            }

            $delay = Get-RetryAfterSeconds `
                -Exception $_.Exception `
                -DefaultSeconds 30

            Write-Host ""
            Write-Host "  Wikimedia request was rate-limited or temporarily failed."
            Write-Host "  Attempt $attempt / $MaxAttempts"
            Write-Host "  Retrying in $delay seconds..."

            Start-Sleep -Seconds $delay
        }
    }
}


function Invoke-WikimediaDownload {

    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,

        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $partialFile = "$Destination.part"

    if (Test-Path $partialFile) {
        Remove-Item $partialFile -Force
    }

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {

        try {

            Write-Host "  Download attempt $attempt / $MaxAttempts"

            Invoke-WebRequest `
                -Uri $Uri `
                -Headers $WikimediaHeaders `
                -OutFile $partialFile `
                -UseBasicParsing

            if (-not (Test-Path $partialFile)) {
                throw "Download completed without creating the expected file."
            }

            $size = (Get-Item $partialFile).Length

            if ($size -le 0) {
                throw "Downloaded file is empty."
            }

            if (Test-Path $Destination) {
                Remove-Item $Destination -Force
            }

            Move-Item `
                -Path $partialFile `
                -Destination $Destination `
                -Force

            Start-Sleep -Seconds $RequestDelaySeconds

            return
        }
        catch {

            if (Test-Path $partialFile) {
                Remove-Item $partialFile -Force -ErrorAction SilentlyContinue
            }

            if ($attempt -eq $MaxAttempts) {
                throw
            }

            $delay = Get-RetryAfterSeconds `
                -Exception $_.Exception `
                -DefaultSeconds 30

            Write-Host ""
            Write-Host "  Wikimedia rate limit or temporary download error."
            Write-Host "  Retrying in $delay seconds..."

            Start-Sleep -Seconds $delay
        }
    }
}


function Get-CommonsMediaInfo {

    param(
        [Parameter(Mandatory = $true)]
        [string]$FileName
    )

    $title = "File:$FileName"

    $encodedTitle = [uri]::EscapeDataString($title)

    $apiUrl =
        "https://commons.wikimedia.org/w/api.php" +
        "?action=query" +
        "&prop=imageinfo" +
        "&iiprop=url%7Csize%7Cextmetadata" +
        "&format=json" +
        "&formatversion=2" +
        "&titles=$encodedTitle"

    $response = Invoke-WikimediaRestRequest -Uri $apiUrl

    if ($null -eq $response.query.pages) {
        throw "Commons did not return page information for: $FileName"
    }

    $page = $response.query.pages | Select-Object -First 1

    if ($null -eq $page) {
        throw "Commons did not return a page for: $FileName"
    }

    if ($page.missing -eq $true) {
        throw "Commons file does not exist: $FileName"
    }

    if ($null -eq $page.imageinfo) {
        throw "Commons returned no media information for: $FileName"
    }

    $info = $page.imageinfo | Select-Object -First 1

    if ($null -eq $info.url) {
        throw "Commons returned no original media URL for: $FileName"
    }


    $license = $null
    $artist = $null
    $credit = $null

    if ($info.extmetadata) {

        if ($info.extmetadata.LicenseShortName) {
            $license = $info.extmetadata.LicenseShortName.value
        }

        if ($info.extmetadata.Artist) {
            $artist = $info.extmetadata.Artist.value
        }

        if ($info.extmetadata.Credit) {
            $credit = $info.extmetadata.Credit.value
        }
    }


    return [pscustomobject]@{
        originalUrl     = $info.url
        descriptionUrl  = $info.descriptionurl
        width           = $info.width
        height          = $info.height
        commonsBytes    = $info.size
        commonsLicense  = $license
        artist           = $artist
        credit           = $credit
    }
}


function Get-RelativeDatasetPath {

    param(
        [Parameter(Mandatory = $true)]
        [string]$RootPath,

        [Parameter(Mandatory = $true)]
        [string]$FullPath
    )

    # Compatible with Windows PowerShell 5.1.
    $normalizedRoot = [System.IO.Path]::GetFullPath($RootPath)

    if (-not $normalizedRoot.EndsWith("\")) {
        $normalizedRoot += "\"
    }

    $normalizedFile = [System.IO.Path]::GetFullPath($FullPath)

    if ($normalizedFile.StartsWith(
        $normalizedRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        return $normalizedFile.Substring(
            $normalizedRoot.Length
        ).Replace("\", "/")
    }

    return $normalizedFile.Replace("\", "/")
}


# -----------------------------------------------------------------------------
# Start
# -----------------------------------------------------------------------------

Write-Host ""
Write-Host "========================================================"
Write-Host " RentReady Vision - External Video Download v1"
Write-Host "========================================================"
Write-Host ""
Write-Host "This script ONLY downloads and organizes source videos."
Write-Host "It does NOT run RentReady Vision."
Write-Host ""
Write-Host "Destination:"
Write-Host "  $Root"
Write-Host ""


New-Item `
    -ItemType Directory `
    -Force `
    -Path $Root |
    Out-Null


$manifestItems = @()
$failures = @()


foreach ($clip in $clips) {

    Write-Host ""
    Write-Host "--------------------------------------------------------"
    Write-Host "[$($clip.id)] $($clip.description)"
    Write-Host "--------------------------------------------------------"
    Write-Host "  Commons file:"
    Write-Host "  $($clip.commonsFile)"

    try {

        Write-Host "  Resolving Wikimedia metadata..."

        $media = Get-CommonsMediaInfo `
            -FileName $clip.commonsFile


        $folder = Join-Path `
            $Root `
            $clip.split

        $folder = Join-Path `
            $folder `
            $clip.class


        New-Item `
            -ItemType Directory `
            -Force `
            -Path $folder |
            Out-Null


        $destination = Join-Path `
            $folder `
            $clip.localName


        if (
            (Test-Path $destination) -and
            -not $Force
        ) {

            $existingSize = (Get-Item $destination).Length

            if ($existingSize -gt 0) {
                Write-Host "  Already downloaded."
                Write-Host "  Existing file will be kept."
            }
            else {
                Remove-Item $destination -Force

                Write-Host "  Existing file was empty."
                Write-Host "  Downloading again..."

                Invoke-WikimediaDownload `
                    -Uri $media.originalUrl `
                    -Destination $destination
            }
        }
        else {

            Write-Host "  Downloading..."

            Invoke-WikimediaDownload `
                -Uri $media.originalUrl `
                -Destination $destination
        }


        if (-not (Test-Path $destination)) {
            throw "Expected downloaded file is missing: $destination"
        }


        $fileInfo = Get-Item $destination

        if ($fileInfo.Length -le 0) {
            throw "Downloaded file is empty: $destination"
        }


        $hash = (
            Get-FileHash `
                -Path $destination `
                -Algorithm SHA256
        ).Hash.ToLower()


        $relativePath = Get-RelativeDatasetPath `
            -RootPath $Root `
            -FullPath $destination


        if ($media.descriptionUrl) {
            $sourcePage = $media.descriptionUrl
        }
        else {
            $sourcePage =
                "https://commons.wikimedia.org/wiki/File:" +
                [uri]::EscapeDataString($clip.commonsFile)
        }


        $manifestItems += [pscustomobject][ordered]@{

            id = $clip.id

            expected_label = $clip.label

            split = $clip.split

            defect_class = $clip.class

            benchmark_role = $clip.role

            description = $clip.description

            local_path = $relativePath

            file_size_bytes = $fileInfo.Length

            sha256 = $hash

            commons_filename = $clip.commonsFile

            source_page = $sourcePage

            original_media_url = $media.originalUrl

            declared_license = $clip.declaredLicense

            commons_license = $media.commonsLicense

            artist = $media.artist

            width = $media.width

            height = $media.height

            downloaded_utc =
                (Get-Date).ToUniversalTime().ToString("o")
        }


        Write-Host ""
        Write-Host "  SUCCESS"
        Write-Host "  Saved:"
        Write-Host "  $relativePath"
        Write-Host ""
        Write-Host "  Size:"
        Write-Host "  $($fileInfo.Length) bytes"
        Write-Host ""
        Write-Host "  SHA256:"
        Write-Host "  $hash"

        if ($media.commonsLicense) {
            Write-Host ""
            Write-Host "  Commons license:"
            Write-Host "  $($media.commonsLicense)"
        }
    }
    catch {

        Write-Warning "FAILED $($clip.id): $($_.Exception.Message)"

        $failures += [pscustomobject][ordered]@{
            id = $clip.id
            commons_filename = $clip.commonsFile
            error = $_.Exception.Message
        }
    }
}


# -----------------------------------------------------------------------------
# Manifest
# -----------------------------------------------------------------------------

$manifest = [ordered]@{

    schema_version = "1.1"

    dataset = "RentReady Vision External Video Sources v1"

    purpose =
        "Downloaded external source videos. " +
        "No RentReady Vision processing has been performed."

    created_utc =
        (Get-Date).ToUniversalTime().ToString("o")

    source =
        "Wikimedia Commons"

    requested_items =
        $clips.Count

    downloaded_items =
        $manifestItems.Count

    failed_items =
        $failures.Count

    processing_status =
        "download_only"

    rentready_processing_performed =
        $false

    items =
        $manifestItems

    failures =
        $failures
}


$manifestPath = Join-Path `
    $Root `
    "manifest.json"


$manifest |
    ConvertTo-Json -Depth 12 |
    Set-Content `
        -Path $manifestPath `
        -Encoding UTF8


# -----------------------------------------------------------------------------
# README
# -----------------------------------------------------------------------------

$readme = @"
# RentReady Vision - External Video Sources v1

This directory currently contains downloaded source videos only.

No RentReady Vision processing has been performed.

Specifically, these videos have NOT been:

- passed through RentReady Vision
- frame-extracted
- scored
- classified
- used for detector tuning
- used for training
- used for evaluation

## Source

Wikimedia Commons.

See `manifest.json` for:

- source page
- source filename
- license
- local path
- SHA-256
- file size
- video dimensions

## Current status

DOWNLOAD ONLY.

"@


$readmePath = Join-Path `
    $Root `
    "README.md"


$readme |
    Set-Content `
        -Path $readmePath `
        -Encoding UTF8


# -----------------------------------------------------------------------------
# Final summary
# -----------------------------------------------------------------------------

Write-Host ""
Write-Host "========================================================"
Write-Host " Download operation complete"
Write-Host "========================================================"
Write-Host ""
Write-Host "Requested:  $($clips.Count)"
Write-Host "Downloaded: $($manifestItems.Count)"
Write-Host "Failed:     $($failures.Count)"
Write-Host ""
Write-Host "Manifest:"
Write-Host "  $manifestPath"
Write-Host ""
Write-Host "README:"
Write-Host "  $readmePath"
Write-Host ""
Write-Host "No RentReady Vision processing was performed."
Write-Host ""


if ($failures.Count -gt 0) {

    Write-Warning "Some downloads failed."

    Write-Host ""
    Write-Host "Failed clips:"

    foreach ($failure in $failures) {
        Write-Host "  $($failure.id) - $($failure.error)"
    }

    exit 1
}


Write-Host "All source videos downloaded successfully."
exit 0
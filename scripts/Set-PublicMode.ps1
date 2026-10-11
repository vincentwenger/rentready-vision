[CmdletBinding()]
param(
    [switch]$Enabled,
    [switch]$Disabled,
    [Nullable[double]]$Hours,
    [Nullable[int]]$MaxVideoMB,
    [Nullable[int]]$MaxInspections,
    [string]$Region = "us-west-2",
    [string]$Table = "rentready-vision-dev",
    [Alias("Profile")][string]$AwsProfile,
    [string]$Endpoint = "https://rentreadyvision.com"
)
$ErrorActionPreference = "Stop"
if ($Enabled -and $Disabled) { throw "Choose Enabled or Disabled." }
$arguments = @("-B", (Join-Path $PSScriptRoot "public_mode_control.py"), "--region", $Region, "--table", $Table, "--endpoint", $Endpoint)
if ($Enabled) { $arguments += "--enabled" }
if ($Disabled) { $arguments += "--disabled" }
if ($PSBoundParameters.ContainsKey("Hours")) { $arguments += @("--hours", ([double]$Hours).ToString([Globalization.CultureInfo]::InvariantCulture)) }
if ($PSBoundParameters.ContainsKey("MaxVideoMB")) { $arguments += @("--max-video-mb", "$MaxVideoMB") }
if ($PSBoundParameters.ContainsKey("MaxInspections")) { $arguments += @("--max-inspections", "$MaxInspections") }
if ($AwsProfile) { $arguments += @("--profile", $AwsProfile) }
& python @arguments
if ($LASTEXITCODE -ne 0) { throw "Public-mode update failed. Settings may be unchanged; run Get-PublicMode.ps1." }

[CmdletBinding()]
param([string]$Region = "us-west-2", [string]$Table = "rentready-vision-dev", [Alias("Profile")][string]$AwsProfile)
$ErrorActionPreference = "Stop"
$arguments = @("-B", (Join-Path $PSScriptRoot "public_mode_control.py"), "--status", "--region", $Region, "--table", $Table)
if ($AwsProfile) { $arguments += @("--profile", $AwsProfile) }
& python @arguments
if ($LASTEXITCODE -ne 0) { throw "Public-mode status lookup failed." }

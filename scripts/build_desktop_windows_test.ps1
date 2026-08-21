param(
  [string]$PythonBin = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VersionLine = Select-String -Path "$Root/client/pyside6/version.py" -Pattern '^APP_VERSION = "([^"]+)"'
$Version = $VersionLine.Matches[0].Groups[1].Value
if ([string]::IsNullOrWhiteSpace($Version)) { throw "Unable to read APP_VERSION." }
$DistDir = Join-Path $Root "release-artifacts"
$Asset = "ModelForge-windows-$Version.zip"

Set-Location $Root
Remove-Item -Force -Recurse -ErrorAction SilentlyContinue build, dist
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
& $PythonBin -m PyInstaller --noconfirm --clean --windowed --name ModelForge --paths client/pyside6 --add-data "client/pyside6/i18n;i18n" --add-data "client/pyside6/theme;theme" --hidden-import cryptography.fernet --hidden-import httpx client/pyside6/main.py
if (-not (Test-Path "dist/ModelForge")) { throw "ModelForge directory was not generated." }
Compress-Archive -Path "dist/ModelForge" -DestinationPath "$DistDir/$Asset" -Force
$Hash = (Get-FileHash -Algorithm SHA256 "$DistDir/$Asset").Hash.ToLower()
"$Hash  $Asset" | Add-Content -Encoding utf8 "$DistDir/checksums.txt"
Write-Output "Windows test asset: $DistDir/$Asset"

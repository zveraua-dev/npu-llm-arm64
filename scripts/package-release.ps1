# Package a release archive with the Hexagon NPU backend artifacts
# (libggml-htp-v*.so + libggml-htp.cat + backend binaries).
# Usage: .\package-release.ps1 [-LabDir D:\npu-llm-lab] [-Version 0.1.0]
param(
    [string]$LabDir = "",
    [string]$Version = "0.1.0",
    [string]$OutDir = "$PSScriptRoot..\dist"
)

if (-not $LabDir) {
    $candidates = @(
        (Join-Path $env:USERPROFILE ".zcode\workspace\npu-llm-lab"),
        (Join-Path (Get-Location).Path "npu-llm-lab"),
        (Split-Path $PSScriptRoot -Parent)
    )
    foreach ($c in $candidates) {
        if (Test-Path (Join-Path $c "bin\hexagon\bin\llama-server.exe")) { $LabDir = $c; break }
    }
}
if (-not $LabDir) { throw "NPU lab build not found; pass -LabDir with a bin\hexagon layout." }

$hexDir = Join-Path $LabDir "bin\hexagon"
if (-not (Test-Path (Join-Path $hexDir "lib\libggml-htp-v81.so"))) {
    throw "libggml-htp-v*.so not found under $hexDir\lib — was the Hexagon build completed?"
}

New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$zip = Join-Path $OutDir "npu-llm-arm64-v$Version-win-arm64.zip"
if (Test-Path $zip) { Remove-Item $zip }

# bin\ + lib\ keep their relative layout; ADSP_LIBRARY_PATH must point at lib\
Compress-Archive -Path (Join-Path $hexDir "bin\*"), (Join-Path $hexDir "lib\*") -DestinationPath $zip

$soFiles = Get-ChildItem (Join-Path $hexDir "lib") -Filter "libggml-htp-*.so"
"Release archive: $zip ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB)"
"HTP libraries included (signing targets):"
$soFiles | ForEach-Object { "  $($_.Name)  ($([math]::Round($_.Length / 1KB)) KB)" }
"  $((Get-Item (Join-Path $hexDir 'lib\libggml-htp.cat')).Name)  (catalog)"

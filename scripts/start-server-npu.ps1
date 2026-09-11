# Start llama-server with the Hexagon NPU backend (Windows on Snapdragon).
# Usage:
#   .\start-server-npu.ps1 -Model "C:\models\gpt-oss-20b-MXFP4.gguf"
#   .\start-server-npu.ps1 -Model .\model.gguf -LabDir D:\npu-llm-lab -Port 8080
param(
    [Parameter(Mandatory = $true)]
    [string]$Model,            # path to a GGUF model (NPU quants: Q4_0, IQ4_NL, MXFP4, Q8_0, F32)
    [string]$LabDir = "",      # dir containing bin\hexagon\{bin,lib}; auto-detected if empty
    [int]$Port = 8080,
    [int]$Ctx = 8192,
    [string]$LogFile = ""
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
if (-not $LabDir -or -not (Test-Path (Join-Path $LabDir "bin\hexagon\bin\llama-server.exe"))) {
    throw "llama-server.exe with the Hexagon backend not found. Build it first (scripts\build-hexagon.cmd) or pass -LabDir."
}

$binDir = Join-Path $LabDir "bin\hexagon\bin"
$libDir = Join-Path $LabDir "bin\hexagon\lib"

# CRITICAL: without ADSP_LIBRARY_PATH FastRPC cannot find libggml-htp-v*.so,
# the HTP session fails with 0x80000406 and llama.cpp silently falls back to CPU/OpenCL.
$env:ADSP_LIBRARY_PATH = $libDir

# --device HTP0 -ngl 99: pin all layers to the NPU. Without these flags the server
# still starts and answers, but the model quietly stays on CPU/OpenCL.
# -lv 5: the log only contains the ggml-hex / offloaded N/N lines at verbosity 5,
# which is how you verify the NPU is actually in use.
$serverArgs = @("-m", $Model, "--host", "127.0.0.1", "--port", $Port, "-c", $Ctx,
                "--device", "HTP0", "-ngl", "99", "-lv", "5")

if (-not $LogFile) { $LogFile = Join-Path $env:TEMP "llama-server-npu.log" }

Write-Host "ADSP_LIBRARY_PATH = $env:ADSP_LIBRARY_PATH"
Write-Host "log: $LogFile"
Write-Host "OpenAI-compatible API: http://127.0.0.1:$Port/v1"
& (Join-Path $binDir "llama-server.exe") @serverArgs 2>&1 | Out-File -FilePath $LogFile -Encoding utf8

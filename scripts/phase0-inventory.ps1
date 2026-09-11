# Фаза 0: инвентаризация системы. Запуск: powershell -File phase0-inventory.ps1
$ErrorActionPreference = "SilentlyContinue"

"=== OS ==="
Get-ComputerInfo | Select-Object WindowsProductName, OsVersion, OsBuildNumber, OsArchitecture | Format-List

"=== CPU / SoC ==="
(Get-CimInstance Win32_Processor) | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors | Format-List

"=== RAM ==="
$os = Get-CimInstance Win32_OperatingSystem
"Total GB: {0:N1}" -f ($os.TotalVisibleMemorySize/1MB)
"Free GB:  {0:N1}" -f ($os.FreePhysicalMemory/1MB)
Get-CimInstance Win32_PageFileUsage | Select-Object Name, AllocatedBaseSize, CurrentUsage | Format-Table

"=== NPU / Hexagon devices ==="
Get-PnpDevice | Where-Object { $_.FriendlyName -match 'Neural|NPU|Hexagon|QAIRT|DirectML' -or $_.Class -eq 'NeuralCompute' } |
  Select-Object Status, Class, FriendlyName, InstanceId | Format-List

"=== GPU (Adreno) ==="
Get-PnpDevice -Class Display | Select-Object Status, FriendlyName | Format-List

"=== Installed AI tools ==="
$tools = "ollama","lms","llama-server","llama-cli","llama-bench","qnn-net-run","python","uv","git","cmake"
foreach ($t in $tools) {
  $cmd = Get-Command $t -ErrorAction SilentlyContinue
  if ($cmd) { "$t : $($cmd.Source)" } else { "$t : NOT FOUND" }
}

"=== LM Studio / AnythingLLM install dirs ==="
foreach ($d in "$env:USERPROFILE\.lmstudio","$env:LOCALAPPDATA\LM-Studio","$env:LOCALAPPDATA\AnythingLLM","$env:USERPROFILE\.ollama") {
  if (Test-Path $d) { "EXISTS: $d" }
}

"=== QAIRT / QNN SDK search ==="
foreach ($root in "C:\Qualcomm","$env:LOCALAPPDATA\Qualcomm","C:\AI","$env:USERPROFILE\qnn") {
  if (Test-Path $root) { Get-ChildItem $root -Depth 2 | Select-Object -First 30 -ExpandProperty FullName }
}

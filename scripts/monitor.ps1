param([int]$Seconds = 10)
# Monitor CPU / GPU / NPU utilization while inference runs
$end = (Get-Date).AddSeconds($Seconds)
$cpuSum = 0; $n = 0; $gpuMax = 0; $npuMax = 0
while ((Get-Date) -lt $end) {
    $cpu = (Get-Counter '\Processor Information(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 1).CounterSamples[0].CookedValue
    $cpuSum += $cpu; $n++
    try {
        Get-Counter '\GPU Engine(*)\Utilization Percentage' -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop |
          ForEach-Object { foreach ($s in $_.CounterSamples) { if ($s.CookedValue -gt $gpuMax) { $gpuMax = $s.CookedValue } } }
    } catch {}
    try {
        Get-Counter '\NPU(*)\Utilization Percentage' -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop |
          ForEach-Object { foreach ($s in $_.CounterSamples) { if ($s.CookedValue -gt $npuMax) { $npuMax = $s.CookedValue } } }
    } catch {}
}
"CPU avg: {0:N0}%  GPU max: {1:N0}%  NPU max: {2:N0}%" -f ($cpuSum/$n), $gpuMax, $npuMax

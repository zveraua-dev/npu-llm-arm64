Get-Counter -ListSet * | Where-Object { $_.CounterSetName -match 'NPU|Neural|Hexagon|Qualcomm|HNP|Compute' } | ForEach-Object {
  "SET: " + $_.CounterSetName
  $_.Paths | Select-Object -First 6 | ForEach-Object { "  " + $_ }
}

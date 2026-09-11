Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 Name, @{n='RAM_GB';e={[math]::Round($_.WorkingSet64/1GB,2)}} | Format-Table
"=== ollama ==="
ollama list
ollama --version

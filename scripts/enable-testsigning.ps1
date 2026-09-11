# RUN IN ELEVATED (ADMIN) PowerShell. One-time setup for NPU backend.
# Right-click Start -> "Terminal (Admin)", then:
#   powershell -ExecutionPolicy Bypass -File <path to this file>

Write-Host "=== 1. Enable test-signing ==="
bcdedit /set TESTSIGNING ON
bcdedit /enum {current} | Select-String testsigning

Write-Host "`n=== 2. Import GGML HTP cert into machine stores ==="
certutil -addstore -f Root "$env:USERPROFILE\Certs\ggml-htp-v1.cer"
certutil -addstore -f TrustedPublisher "$env:USERPROFILE\Certs\ggml-htp-v1.cer"

Write-Host "`n=== 3. Secure Boot check ==="
try {
    $sb = Confirm-SecureBootUEFI
    Write-Host "Secure Boot: $sb"
    if ($sb) {
        Write-Host "!!! Secure Boot is ON. Test-signing may not take effect."
        Write-Host "Reboot into BIOS (F2 on ASUS at boot) -> disable Secure Boot -> save -> reboot."
    }
} catch { Write-Host "Secure Boot state unknown: $($_.Exception.Message)" }

Write-Host "`nDone. REBOOT required. After reboot a 'Test Mode' watermark appears - that's expected."
Write-Host "Rollback later: bcdedit /set TESTSIGNING OFF (plus re-enable Secure Boot in BIOS)."

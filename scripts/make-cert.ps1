# Create self-signed code signing cert for HTP libs (no admin needed)
$certDir = "$env:USERPROFILE\Certs"
New-Item -ItemType Directory -Path $certDir -Force | Out-Null

$existing = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object Subject -eq "CN=GGML.HTP.v1"
if ($existing) {
    "Cert already exists: $($existing.Thumbprint)"
    $cert = $existing
} else {
    $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=GGML.HTP.v1" `
        -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(5)
    "Created cert: $($cert.Thumbprint)"
}

$pfxPath = "$certDir\ggml-htp-v1.pfx"
$pwd = ConvertTo-SecureString -String "npu-llm-lab" -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $pwd | Out-Null
"PFX saved: $pfxPath (password: npu-llm-lab)"

Export-Certificate -Cert $cert -FilePath "$certDir\ggml-htp-v1.cer" | Out-Null
Import-Certificate -FilePath "$certDir\ggml-htp-v1.cer" -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
Import-Certificate -FilePath "$certDir\ggml-htp-v1.cer" -CertStoreLocation Cert:\CurrentUser\TrustedPublisher | Out-Null
"Cert imported into current-user Root and TrustedPublisher stores."
"NOTE: if NPU backend load fails with signature error, the cert must be"
"imported into LOCAL MACHINE stores (certlm.msc) which requires admin."

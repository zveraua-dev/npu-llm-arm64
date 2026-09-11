# NPU driver signing on Windows: why, and the road to a trusted certificate

## The problem

The Hexagon (HTP) NPU backend of llama.cpp on Windows on Snapdragon loads
`libggml-htp-v73/v75/v79/v81.so` through the FastRPC driver. The driver
refuses to load libraries that are not code-signed with a certificate
chaining to a trusted root.

Upstream llama.cpp does not ship signed Windows-on-Snapdragon builds, so
today every user has to either:

1. **sign the libraries with a self-signed certificate themselves**
   (`scripts/make-cert.ps1`), import it into the machine `Root` and
   `TrustedPublisher` stores, enable **test-signing** (`bcdedit /set
   TESTSIGNING ON`) and disable Secure Boot — see
   `scripts/enable-testsigning.ps1`; or
2. not use the NPU at all.

Option 1 works, but it is unacceptable as a default for normal users: it
weakens the boot chain for the whole OS and leaves a "Test Mode" watermark
on the desktop. It is fine for development and benchmarks only.

## The goal of this project

Distribute **publicly trusted, OV-level code-signed** builds of the Hexagon
backend libraries so the NPU works out of the box, with Secure Boot on and
test-signing off.

We are applying to the [SignPath Foundation](https://signpath.org/) open
source program, which provides free code signing certificates and a signing
service for open source projects (certificate level: OV; keys stay in their
HSM; binaries are signed in their cloud after a per-release approval).

Fallback option if the application is not accepted:
[Certum Open Source](https://www.certum.eu/en/open-source-code-signing/)
(~€90/year, cloud or token key).

## What gets signed

The release artifacts of this project that the FastRPC driver loads:

- `libggml-htp-v73.so`, `libggml-htp-v75.so`, `libggml-htp-v79.so`,
  `libggml-htp-v81.so` — Hexagon DSP libraries for each HTP architecture
  generation (v73 = 8cx Gen3, v75 = X Elite, v79 = X2 Elite, v81 = X2 Elite
  Extreme — mapping documented by Qualcomm);
- `libggml-htp.cat` — the signed catalog accompanying them;
- `ggml-hexagon.dll` / host-side backend binaries in release archives.

## Verification

Once a signed release exists:

```powershell
Get-AuthenticodeSignature .\libggml-htp-v81.so | Format-List
signtool verify /pa /v .\libggml-htp-v81.so
```

On a clean Windows 11 ARM64 machine with Secure Boot **on** and
test-signing **off**: start `llama-server` with `--device HTP0 -ngl 99 -lv 5`
and confirm the log contains `ggml-hex: Hexagon backend` and
`offloaded N/N layers` — see `llm_engines.py` / `bench/bench_extract.py`.

## Status

- [x] Self-signed test-signing flow works (NPU confirmed at >95% utilization)
- [x] Reproducible build script for the Hexagon backend (`scripts/build-hexagon.cmd`)
- [ ] Publicly trusted signing via SignPath Foundation (application submitted)
- [ ] Test-signing-free release verified on a clean machine

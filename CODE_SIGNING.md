# Code Signing Policy

This document describes how the **npu-llm-arm64** project signs its release
artifacts. Free code signing is provided by
[SignPath.io](https://signpath.io) and the
[SignPath Foundation](https://signpath.org) open source program — we gratefully
acknowledge their support.

## What is signed

Release artifacts published on the GitHub *Releases* page of this repository,
primarily the Hexagon NPU backend libraries loaded by the Windows FastRPC
driver (`libggml-htp-v*.so`, `libggml-htp.cat`, and the backend binaries in
release archives). Binaries are built from the sources of this repository and
its documented build pipeline (`scripts/build-hexagon.cmd`).

## Signing process

- All binaries are built from the public git history of this repository.
- Signing keys are generated and kept in a Hardware Security Module operated
  by SignPath.io; they are non-exportable and never available to the project
  team.
- Every signing request must be approved by a project Approver (see roles
  below) before SignPath executes it.

## Team roles

| Role | Person | Responsibility |
|---|---|---|
| Author / Reviewer / Approver | zveraua-dev (maintainer) | commits, reviews external PRs, approves signing requests |

The project currently has a single maintainer; all three roles (Authors,
Reviewers, Approvers per the SignPath Foundation terms) are held by that
person. All repository and SignPath accounts use multi-factor authentication.

## Privacy

This project collects no personal data. The tools run locally; the LLM
endpoints they talk to (a local llama-server or a local Ollama instance) are
configured by the user. No telemetry is sent anywhere.

## Verification

```powershell
Get-AuthenticodeSignature .\libggml-htp-v81.so | Format-List Subject, SignerCertificate, Status
signtool verify /pa /v .\libggml-htp-v81.so
```

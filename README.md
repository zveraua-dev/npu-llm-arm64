# npu-llm-arm64

Run LLMs on the **NPU (Qualcomm Hexagon)** of Windows-on-Snapdragon laptops —
with an engine that detects the NPU honestly, and tools to build, benchmark
and sign the backend.

Tested on: ASUS Zenbook A16, Snapdragon X2 Elite Extreme, 48 GB RAM,
Windows 11 ARM64.

## Why

Windows on ARM laptops ship with a capable NPU that almost nobody uses.
llama.cpp has an experimental Hexagon (HTP) backend for it, but on Windows it
is hard to consume:

- it requires a custom build with the Hexagon SDK;
- the FastRPC driver only loads **code-signed** `libggml-htp-v*.so` libraries
  — upstream does not sign them, so users must enable test-signing with a
  self-signed certificate (see [docs/NPU-SIGNING.md](docs/NPU-SIGNING.md));
- the supported quants are limited (`Q4_0, IQ4_NL, MXFP4, Q8_0, F32`);
- if anything is wrong, llama.cpp **silently** falls back to CPU/OpenCL and
  you benchmark the wrong silicon.

This repo packages the working solution: build scripts, a runtime engine with
honest NPU detection and Ollama fallback, a synthetic extract-workload
benchmark, and a quant planner.

## Real-world results (gpt-oss-20b, MXFP4, same laptop)

| Configuration | prompt processing (pp512) | generation (tg400) | CPU load | NPU |
|---|---:|---:|---|---|
| CPU (18 cores) | ~131 t/s | ~34.7 t/s | ~100% | 0% |
| OpenCL + HTP (Adreno + NPU) | **670 t/s** | 22.2 t/s | ~21% | **>95%** |

For long-input/short-output workloads (summarization, extraction,
classification) that is an end-to-end win: a 250-document extraction batch
dropped from ~7.8 h (CPU) to ~2.2 h (NPU), with a cooler and quieter machine.

## Repository layout

| Path | What it is |
|---|---|
| `llm_engines.py` | Runtime engine: NPU detection, llama-server lifecycle, honest fallback to Ollama (stdlib only) |
| `bench/bench_extract.py` | Synthetic extract-workload benchmark for any OpenAI-compatible endpoint |
| `bench/quant_calc.py` | Quant size / NPU-compatibility / RAM-fit calculator |
| `scripts/build-hexagon.cmd` | Build llama.cpp with the Hexagon + OpenCL backends (requires Hexagon SDK) |
| `scripts/make-cert.ps1` | Create + import the self-signed HTP cert (dev/test-signing flow) |
| `scripts/enable-testsigning.ps1` | One-time test-signing setup (admin); rollback included |
| `scripts/start-server-npu.ps1` | Start llama-server with the right env + NPU flags |
| `scripts/monitor.ps1` | Watch CPU/GPU/NPU utilization during inference |
| `docs/` | Snapdragon platform guides (vendored from llama.cpp) and [NPU signing notes](docs/NPU-SIGNING.md) |

## Quick start (NPU)

1. Build llama.cpp with the Hexagon backend (or use a release archive):

   ```powershell
   # one-time: Hexagon SDK 6.6+, OpenCL SDK 2.3+, VS 2026 with ARM64 tools
   scripts\build-hexagon.cmd
   ```

2. One-time dev setup for the unsigned upstream libraries (test-signing;
   see [docs/NPU-SIGNING.md](docs/NPU-SIGNING.md) for why signed releases
   will remove this step):

   ```powershell
   scripts\make-cert.ps1            # create + import self-signed cert
   scripts\enable-testsigning.ps1   # admin; reboot required
   ```

3. Use the engine:

   ```python
   import llm_engines
   chat = llm_engines.ensure_chat(engine="auto", ollama_model="qwen3.5:4b")
   answer, elapsed = chat("model", "Summarize: ...")
   ```

   `ensure_chat` starts llama-server with `--device HTP0 -ngl 99 -lv 5`,
   checks the log for `ggml-hex: Hexagon backend` and only then keeps the
   NPU path; otherwise it falls back to Ollama and tells you why.

4. Benchmark it:

   ```powershell
   scripts\start-server-npu.ps1 -Model C:\models\gpt-oss-20b-MXFP4.gguf
   python bench\bench_extract.py --prompt-chars 12000 --rounds 3
   ```

## Gotchas (learned the hard way)

- `ADSP_LIBRARY_PATH` must point at `bin\hexagon\lib` **in the same
  session** llama-server starts from; otherwise FastRPC fails with
  `0x80000406` and the backend silently dies.
- Without `--device HTP0 -ngl 99` the server starts fine and quietly runs on
  CPU/OpenCL.
- The `ggml-hex` log lines only appear at `-lv 5`.
- NPU quants only: `Q4_0, IQ4_NL, MXFP4, Q8_0, F32`. A `Q4_K_M` GGUF will
  run — on the CPU.
- The KV cache is not quantized on the NPU: budget RAM accordingly
  (`bench/quant_calc.py`).

## Code signing

Releases are intended to be signed through the
[SignPath Foundation](https://signpath.org/) open source program so the NPU
works without test-signing. See [CODE_SIGNING.md](CODE_SIGNING.md) for the
signing policy.

## License

[MIT](LICENSE), except `scripts/vendor-llama_cpp_setup.ps1`
(BSD-3-Clause, © Qualcomm Innovation Center) and the vendored platform guides
in `docs/` (from the llama.cpp project, MIT).

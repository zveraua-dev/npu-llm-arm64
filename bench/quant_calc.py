# -*- coding: utf-8 -*-
"""Quantization calculator for NPU planning on Windows-on-Snapdragon.

The Hexagon NPU backend of llama.cpp only executes these quants on the NPU:
Q4_0, IQ4_NL, MXFP4, Q8_0, F32 — anything else (Q4_K_M, Q5_K_M, IQ4_XS, ...)
silently runs on CPU/OpenCL. The KV cache is not quantized on the NPU, so
long contexts need extra RAM beyond the weights.

This tool answers the practical questions:
  * how big will a model be in each quant?
  * which quants will actually use the NPU?
  * what fits into the RAM this machine has right now?

Usage:
  python quant_calc.py 8B              # 8-billion-parameter model
  python quant_calc.py 20B --ctx 32768 # include KV-cache overhead for 32k context
  python quant_calc.py --list-models   # known reference sizes (MoE included)
"""
import argparse
import ctypes
import sys

# bits per weight for each quant family (approximate, good for planning)
QUANT_BITS = {
    "Q4_0": 4.5, "IQ4_NL": 4.5, "Q4_K_M": 4.85, "Q5_K_M": 5.7,
    "Q6_K": 6.6, "IQ4_XS": 4.25, "Q8_0": 8.5, "F16": 16.0, "BF16": 16.0,
    "F32": 32.0, "MXFP4": 4.25,
}
NPU_QUANTS = {"Q4_0", "IQ4_NL", "MXFP4", "Q8_0", "F32"}

# reference models: (name, total params in billions, active params in billions)
MODELS = {
    "qwen3.5-4b": (4.0, 4.0),
    "qwen3.5-9b": (9.0, 9.0),
    "gemma4-12b": (12.0, 12.0),
    "deepseek-r1-0528-qwen3-8b": (8.0, 8.0),
    "gpt-oss-20b": (20.9, 3.6),   # MoE: 3.6B active
    "qwen3.5-32b": (32.0, 32.0),
}

RAM_HEADROOM_GB = 1.5  # OS + runtime + fragmentation
# KV cache is NOT quantized on the NPU. Rough floor per token per layer:
# 2 (K+V) * 8 GQA heads * 128 head_dim * 2 bytes (fp16) = 4096 bytes.
KV_BYTES_PER_TOKEN_PER_LAYER = 4096


def free_ram_gb() -> float:
    if sys.platform != "win32":
        return 0.0
    class MEMSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MEMSTATUSEX()
    m.dwLength = ctypes.sizeof(MEMSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return round(m.ullAvailPhys / 1024 ** 3, 1)


def model_gb(params_b: float, quant: str) -> float:
    return params_b * 1e9 * QUANT_BITS[quant] / 8 / 1024 ** 3


def kv_gb(params_b: float, active_b: float, ctx: int) -> float:
    # rough estimate: layer count scales with total params (~0.6B/layer),
    # clamped to what current model families actually use
    layers = min(80, max(16, round(params_b / 0.6)))
    return layers * ctx * KV_BYTES_PER_TOKEN_PER_LAYER / 1024 ** 3


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("params", nargs="?", help="parameter count, e.g. 8B, 20.9B or 8e9")
    ap.add_argument("--active", type=float, default=None,
                    help="active params for MoE models (e.g. 3.6 for gpt-oss-20b)")
    ap.add_argument("--ctx", type=int, default=8192, help="context length for KV overhead")
    ap.add_argument("--list-models", action="store_true")
    args = ap.parse_args()

    if args.list_models:
        for name, (total, active) in sorted(MODELS.items()):
            npu = ", ".join(q for q in ("Q4_0", "IQ4_NL", "MXFP4")
                            if model_gb(total, q) + RAM_HEADROOM_GB <= 16)
            print(f"{name:32s} total {total:5.1f}B active {active:4.1f}B   "
                  f"fits-16GB-NPU: {npu or '-'}")
        return

    if not args.params:
        ap.error("give a parameter count (8B) or --list-models")
    p = args.params.upper().replace("B", "")
    params_b = float(p)

    ram = free_ram_gb()
    print(f"model: {params_b}B params | context {args.ctx} | free RAM: {ram} GB")
    print(f"{'quant':8s} {'size GB':>8s} {'+KV GB':>7s} {'NPU':>4s}  fits")
    for q in sorted(QUANT_BITS, key=lambda x: QUANT_BITS[x]):
        size = model_gb(params_b, q)
        kv = kv_gb(params_b, args.active or params_b, args.ctx)
        fits = (size + kv + RAM_HEADROOM_GB <= ram) if ram else None
        mark = "yes" if fits else ("?" if fits is None else "NO")
        print(f"{q:8s} {size:8.1f} {kv:7.1f} {'YES' if q in NPU_QUANTS else ' - ':>4s}  {mark}")
    print("\nNPU column: quants the Hexagon backend executes on the NPU;")
    print("everything else silently falls back to CPU/OpenCL.")


if __name__ == "__main__":
    main()

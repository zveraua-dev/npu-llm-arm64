# -*- coding: utf-8 -*-
"""Benchmark the extract workload profile: a LONG input prompt with a SHORT
expected output (summarization / classification / extraction). This is the
profile where an NPU shines: prompt processing (pp) is ~5x faster than CPU,
while generation (tg) is somewhat slower.

The workload is fully SYNTHETIC — no real documents are needed. It builds
repetitive "document-like" inputs of a configurable length, sends them to an
OpenAI-compatible endpoint (llama-server with the Hexagon backend, or any
other server: Ollama's OpenAI API, LM Studio, vLLM...) and reports wall time
plus the server-reported prompt/generation token rates.

Usage:
  python bench_extract.py                       # NPU llama-server on :8080
  python bench_extract.py --url http://127.0.0.1:11434/v1 --model qwen3.5:4b
  python bench_extract.py --prompt-chars 24000 --rounds 5
"""
import argparse
import json
import statistics
import time
import urllib.request

NPU_QUANTS = {"Q4_0", "IQ4_NL", "MXFP4", "Q8_0", "F32"}

_FILLER = (
    "The quarterly maintenance window covered thirteen regional nodes. "
    "Engineers replaced cooling modules, re-routed two distribution lines "
    "and re-registered meters after firmware updates. No incidents were "
    "recorded during the night shift. A follow-up inspection is planned "
    "for the next business week. "
)

_TASK = (
    "Summarize the log above in exactly one sentence and output a JSON "
    "object {\"summary\": string, \"incidents\": integer}. No other text."
)


def synthetic_doc(chars: int) -> str:
    body = (_FILLER * (chars // len(_FILLER) + 1))[:chars]
    return body


def run_round(url: str, model: str, doc: str, num_predict: int,
              timeout: int) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": doc + "\n\n---\n\n" + _TASK}],
        "temperature": 0.1, "max_tokens": num_predict, "stream": False,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
    wall = time.time() - t0
    u = d.get("usage", {})
    pd, gd = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    # a few servers report durations in ms
    pd_s = (u.get("prompt_eval_duration") or 0) / 1e9 if "prompt_eval_duration" in u else None
    return {"wall_s": wall, "prompt_tokens": pd, "gen_tokens": gd,
            "prompt_tps": pd / wall if wall else 0.0,
            "gen_tps": gd / wall if wall else 0.0}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:8080/v1",
                    help="OpenAI-compatible base URL (default: llama-server on :8080)")
    ap.add_argument("--model", default="default",
                    help='model name; llama-server accepts the GGUF file name')
    ap.add_argument("--prompt-chars", type=int, default=12000,
                    help="length of the synthetic input document in characters")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--num-predict", type=int, default=200)
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    doc = synthetic_doc(args.prompt_chars)
    print(f"endpoint: {args.url}  model: {args.model}")
    print(f"input: {args.prompt_chars} chars/round, {args.rounds} rounds, "
          f"max {args.num_predict} output tokens")
    # warm-up round (model load, graph build) — not counted
    try:
        run_round(args.url, args.model, doc, args.num_predict, args.timeout)
    except Exception as e:
        raise SystemExit(f"warm-up request failed: {e}\nIs the server running?")

    rows = []
    for i in range(1, args.rounds + 1):
        r = run_round(args.url, args.model, doc, args.num_predict, args.timeout)
        rows.append(r)
        print(f"  round {i}: wall {r['wall_s']:6.1f}s | "
              f"prompt {r['prompt_tokens']:6d} tok ({r['prompt_tps']:6.0f} t/s) | "
              f"gen {r['gen_tokens']:4d} tok ({r['gen_tps']:5.1f} t/s)")

    def avg(k):
        return statistics.mean(r[k] for r in rows)

    print("-" * 60)
    print(f"AVG: wall {avg('wall_s'):.1f}s | prompt {avg('prompt_tps'):.0f} t/s | "
          f"gen {avg('gen_tps'):.1f} t/s")
    print("Remember to verify the NPU is actually engaged: the llama-server")
    print("log must contain 'ggml-hex: Hexagon backend' and 'offloaded N/N'")
    print("lines (start it with -lv 5, e.g. via scripts/start-server-npu.ps1).")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""LLM engine manager for Windows on Snapdragon: NPU (llama-server with the
Hexagon backend) with an honest fallback to Ollama (CPU/GPU).

Why: llama.cpp with the Hexagon NPU backend gives ~5x faster prompt
processing on long-input / short-output workloads (summarization,
extraction, classification). But the NPU path requires: (1) a special
llama-server build (see scripts/build-hexagon.cmd), (2) the
ADSP_LIBRARY_PATH environment variable set IN THE SAME SESSION, (3) a model
quantized with one of {Q4_0, IQ4_NL, MXFP4, Q8_0, F32}. If any of these is
missing, llama.cpp SILENTLY falls back to CPU/OpenCL — so after the server
starts, its log is checked for "ggml-hex" lines: none found means the NPU
is not working and we fall back to Ollama honestly.

Public API:
  npu_capable()      -> (ok, reason)  fast detection for GUIs/menus
  list_gguf_models() -> [models]      quant + NPU support + free RAM
  free_ram_gb()      -> float
  ensure_chat(engine, gguf, ollama_model, ollama_host, port)
                     -> callable      same signature as a plain chat();
                                       starts llama-server, checks the NPU,
                                       falls back to Ollama (engine="auto")
  state_summary()    -> dict          for status files / dashboards
  stop_server()                      stops llama-server (also via atexit)
"""
import atexit
import ctypes
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

# NPU lab directory (llama.cpp build with the Hexagon backend). Override with
# the NPU_LAB_DIR environment variable; otherwise common locations are tried.
_LAB_CANDIDATES = [
    Path.home() / ".zcode" / "workspace" / "npu-llm-lab",
    HERE.parent / "npu-llm-lab",
    HERE / "npu-llm-lab",
]

# Quants the Hexagon backend executes on the NPU. Everything else
# (Q4_K_M, Q5_K_M, Q6_K, IQ4_XS, F16/BF16 ...) silently goes to CPU/OpenCL.
NPU_QUANTS = {"Q4_0", "IQ4_NL", "MXFP4", "Q8_0", "F32"}
# Extra NPU memory/RAM headroom a quant needs beyond the weights
# (the KV cache is not quantized on the NPU):
RAM_HEADROOM_GB = 1.5


def npu_lab_dir() -> Path | None:
    env = os.environ.get("NPU_LAB_DIR")
    if env and (Path(env) / "bin" / "hexagon" / "bin").is_dir():
        return Path(env)
    for c in _LAB_CANDIDATES:
        if (c / "bin" / "hexagon" / "bin").is_dir():
            return c
    return None


def llama_bin() -> Path | None:
    lab = npu_lab_dir()
    if not lab:
        return None
    exe = lab / "bin" / "hexagon" / "bin" / "llama-server.exe"
    return exe if exe.is_file() else None


def htp_lib_dir() -> Path | None:
    """Directory with libggml-htp-v*.so — the ADSP_LIBRARY_PATH value."""
    lab = npu_lab_dir()
    if not lab:
        return None
    lib = lab / "bin" / "hexagon" / "lib"
    if lib.is_dir() and any(lib.glob("libggml-htp-*.so")):
        return lib
    return None


def free_ram_gb() -> float:
    """Free physical memory (ctypes, stdlib only — no psutil)."""
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


def battery() -> dict:
    """Battery charge and AC state (a long run on battery has bitten us before)."""
    class SYSPOW(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                    ("BatteryLifePercent", ctypes.c_byte), ("Reserved1", ctypes.c_byte),
                    ("BatteryLifeTime", ctypes.c_ulong),
                    ("BatteryFullLifeTime", ctypes.c_ulong)]
    s = SYSPOW()
    s.ACLineStatus = 255
    if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return {"ac": s.ACLineStatus == 1, "percent": s.BatteryLifePercent}
    return {"ac": None, "percent": None}


_QUANT_RE = re.compile(
    r"(IQ4_XS|IQ4_NL|IQ[0-9]_[A-Z0-9]+|Q\d+_K_[A-Z]|Q\d+_[0-9]+|Q\d+|MXFP4|F16|BF16|F32)",
    re.IGNORECASE)


def quant_of(filename: str) -> str:
    m = _QUANT_RE.search(Path(filename).stem)
    return (m.group(1).upper() if m else "").replace("_K_", "_K_")


def _model_dirs() -> list[Path]:
    dirs = []
    lab = npu_lab_dir()
    if lab:
        dirs.append(lab / "models")
    lm = Path.home() / ".lmstudio" / "models"
    if lm.is_dir():
        dirs.append(lm)
    local = HERE / "models"  # GGUF files can simply sit next to the program
    if local.is_dir():
        dirs.append(local)
    return [d for d in dirs if d.is_dir()]


def list_gguf_models() -> list[dict]:
    """All .gguf files in known directories: size, quant, NPU suitability,
    whether it fits in free memory. Sorted: NPU-capable first, then by size
    (bigger = smarter first)."""
    out, seen = [], set()
    ram = free_ram_gb()
    for d in _model_dirs():
        try:
            files = sorted(d.rglob("*.gguf"))
        except OSError:
            continue
        for f in files:
            if str(f).lower() in seen:
                continue
            seen.add(str(f).lower())
            try:
                size_gb = round(f.stat().st_size / 1024 ** 3, 2)
            except OSError:
                continue
            q = quant_of(f.name)
            out.append({"name": f.name, "path": str(f), "size_gb": size_gb,
                        "quant": q, "npu_ok": q in NPU_QUANTS,
                        "fits_ram": size_gb + RAM_HEADROOM_GB <= ram})
    out.sort(key=lambda m: (not m["npu_ok"], -m["size_gb"]))
    return out


def npu_capable() -> tuple[bool, str]:
    """Fast NPU availability check (does not start the server).
    The full check (test-signing, driver) only happens at server start:
    ensure_chat looks for "ggml-hex" in the log and falls back if absent."""
    exe = llama_bin()
    if exe is None:
        return False, "llama.cpp NPU build not found (npu-llm-lab/bin/hexagon)"
    lib = htp_lib_dir()
    if lib is None:
        return False, "libggml-htp-*.so not found (bin/hexagon/lib)"
    if os.environ.get("NPU_DISABLED"):
        return False, "disabled via the NPU_DISABLED environment variable"
    return True, f"llama-server: {exe}"


# ---------------------------------------------------------------- llama-server
_SRV = {"proc": None, "model": None, "port": 8080, "log": None, "npu_active": False}
_STATE = {"engine": None, "detail": "", "model": None, "server_log": None}


def _log_path() -> Path:
    return HERE / "llama_server.log"


def _http_get(url: str, timeout: float = 5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def server_health(port: int) -> dict | None:
    try:
        return _http_get(f"http://127.0.0.1:{port}/health")
    except Exception:
        return None


def npu_active_in_log(log_path: Path, min_bytes: int = 0) -> bool:
    """The NPU really works only if the server (started with -lv 5) logged the
    backend initialization «ggml-hex: Hexagon backend» and/or offloaded layers
    to the HTP0 device («offloaded N/N layers» + HTP0 buffers). A mere mention
    of HTP0 («device HTP0 did not report memory») is NOT proof: the device is
    registered, but the model may still run on CPU/OpenCL."""
    try:
        size = log_path.stat().st_size
        if size < min_bytes:
            return False
        text = log_path.read_text(encoding="utf-8", errors="replace")
        return ("ggml-hex: Hexagon backend" in text
                or ("offloaded" in text and "HTP0 compute buffer" in text))
    except OSError:
        return False


def start_server(model_path: str, port: int = 8080, ctx: int = 8192,
                 timeout_s: int = 300) -> dict:
    """Start llama-server with ADSP_LIBRARY_PATH set (critical: without it
    FastRPC cannot see libggml-htp and the HTP session silently dies). If a
    server with THE SAME model is already alive on the port, it is reused."""
    h = server_health(port)
    if h is not None and h.get("status") == "ok" and _SRV["proc"] is not None \
            and _SRV["model"] == str(Path(model_path).resolve()) and _SRV["proc"].poll() is None:
        return {"ok": True, "reused": True, "npu_active": _SRV["npu_active"]}
    stop_server()  # a foreign/stale server on the port is not good for us

    exe, lib = llama_bin(), htp_lib_dir()
    if not exe or not lib:
        return {"ok": False, "error": "llama.cpp NPU build not found"}
    model_path = str(Path(model_path).resolve())
    if not Path(model_path).is_file():
        return {"ok": False, "error": f"model file not found: {model_path}"}

    log = _log_path()
    env = dict(os.environ)
    env["ADSP_LIBRARY_PATH"] = str(lib)  # required IN THE SAME SESSION
    creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    # --device HTP0 -ngl 99: explicitly put all layers on the NPU (otherwise
    # llama.cpp picks the device itself and the model quietly stays on
    # CPU/OpenCL); -lv 5: otherwise the log has neither ggml-hex nor the
    # offload lines — nothing to verify the NPU against.
    with open(log, "w", encoding="utf-8") as lf:
        _SRV["proc"] = subprocess.Popen(
            [str(exe), "-m", model_path, "--host", "127.0.0.1",
             "--port", str(port), "-c", str(ctx),
             "--device", "HTP0", "-ngl", "99", "-lv", "5"],
            stdout=lf, stderr=subprocess.STDOUT, env=env,
            creationflags=creationflags, cwd=str(exe.parent))
    _SRV.update(model=model_path, port=port, log=log, npu_active=False)

    t0 = time.time()
    while time.time() - t0 < timeout_s:
        h = server_health(port)
        if h is not None and h.get("status") == "ok":
            _SRV["npu_active"] = npu_active_in_log(log)
            return {"ok": True, "reused": False, "npu_active": _SRV["npu_active"],
                    "log": str(log), "pid": _SRV["proc"].pid}
        if _SRV["proc"].poll() is not None:
            tail = _log_tail(log, 1500)
            return {"ok": False, "error": f"llama-server died (code "
                                          f"{_SRV['proc'].returncode}). {tail}"}
        time.sleep(1.0)
    stop_server()
    return {"ok": False, "error": f"llama-server did not answer within {timeout_s}s. "
                                  f"{_log_tail(log, 1500)}"}


def _log_tail(log: Path, n: int) -> str:
    try:
        return "…".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def stop_server() -> None:
    p = _SRV["proc"]
    _SRV.update(proc=None, model=None, npu_active=False)
    if p is not None and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


atexit.register(stop_server)


def state_summary() -> dict:
    return {"engine": _STATE["engine"], "detail": _STATE["detail"],
            "model": _STATE["model"], "npu_active": _SRV["npu_active"],
            "server_log": str(_SRV["log"]) if _SRV["log"] else None}


def pick_model(gguf: str | None, prefer_family: str | None = None) -> str | None:
    """An explicit path is checked as-is; otherwise the best NPU-capable model.
    prefer_family is an Ollama-style tag of the primary engine (e.g.
    "qwen3.5:4b"): if a GGUF of THE SAME model with an NPU quant lies in the
    model directories (Qwen3.5-4B-Q4_0), it is picked; otherwise the largest
    capable model (bigger models are smarter)."""
    if gguf:
        return gguf if Path(gguf).is_file() else None
    models = [m for m in list_gguf_models() if m["npu_ok"] and m["fits_ram"]]
    fam = (prefer_family or "").replace(":", "-").lower()
    for m in models:
        if fam and fam in m["path"].lower():
            return m["path"]
    return models[0]["path"] if models else None


# ---------------------------------------------------------------- chat() adapters
def make_openai_chat(base_url: str, model_name: str, num_ctx: int = 8192):
    """chat() with a plain signature, but talking to the OpenAI-compatible
    API of llama-server. The answer is wrapped into Ollama's shape
    ({"message": {"content": ...}}) so call sites don't change.
    chat_template_kwargs disables thinking in the Qwen3 family; if the server
    template does not understand it, the request is retried without it."""
    url = base_url.rstrip("/") + "/v1/chat/completions"

    def _call(model, user, system="", timeout=600, num_predict=280,
              temperature=0.1, **kw):
        payload = {
            "model": model_name,
            "messages": [{"role": "system", "content": system or ""},
                         {"role": "user", "content": user}],
            "temperature": temperature, "max_tokens": num_predict,
            "stream": False,
        }
        for extra in ({"chat_template_kwargs": {"enable_thinking": False}}, {}):
            body = json.dumps({**payload, **extra}).encode("utf-8")
            req = urllib.request.Request(url, data=body,
                                         headers={"Content-Type": "application/json"})
            t0 = time.time()
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    d = json.loads(r.read().decode("utf-8"))
                content = d["choices"][0]["message"].get("content") or ""
                return ({"message": {"content": content},
                         "_usage": d.get("usage", {})}), time.time() - t0
            except urllib.error.HTTPError as e:
                if e.code == 400 and extra:
                    continue  # chat template unaware of enable_thinking — retry
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="replace")[:300]
                except Exception:
                    pass
                raise RuntimeError(f"llama-server {url} error {e.code}: {detail}") from e
        raise RuntimeError("llama-server: both request variants rejected (400)")

    return _call


def make_ollama_chat(host: str = "http://127.0.0.1:11434"):
    """Standalone chat() over the native Ollama /api/chat API (stdlib only).
    Returns (answer, elapsed_seconds); the answer uses the same
    {"message": {"content": ...}} shape as the llama-server adapter."""
    url = host.rstrip("/") + "/api/chat"

    def _call(model, user, system="", timeout=600, num_predict=280,
              temperature=0.1, **kw):
        payload = {"model": model, "messages": [
                       {"role": "system", "content": system or ""},
                       {"role": "user", "content": user}],
                   "stream": False, "options": {
                       "temperature": temperature, "num_predict": num_predict}}
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"ollama {url} error {e.code}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"ollama {url} unreachable: {e.reason}") from e
        return d, time.time() - t0

    return _call


def ensure_chat(engine: str = "auto", gguf: str | None = None,
                ollama_model: str = "gemma4:latest",
                ollama_host: str | None = None, port: int = 8080,
                verbose: bool = True):
    """Pick an engine and return a chat() function. engine: auto|npu|ollama.
    auto: NPU if the build exists and the model fits, otherwise Ollama.
    npu: same, but raises instead of falling back. The Ollama host is chosen
    by the CALLER (ollama_host); if your project already has its own chat()
    talking to Ollama, keep using it and only take the NPU path from here."""
    def say(msg):
        if verbose:
            print(f"[engine] {msg}", flush=True)

    def ollama_chat():
        # Prefer the caller's existing chat() (drop-in integration); otherwise
        # use the standalone stdlib Ollama client.
        try:
            import common  # local import — breaks the import cycle
            if ollama_host:
                common.OLLAMA_URL = ollama_host
            return common.chat
        except ImportError:
            return make_ollama_chat(ollama_host or "http://127.0.0.1:11434")

    if engine in ("npu", "auto"):
        ok, why = npu_capable()
        model = pick_model(gguf, prefer_family=ollama_model) if ok else None
        if not ok or not model:
            msg = (f"NPU unavailable ({why})" if not ok
                   else "no GGUF model with an NPU quant "
                        f"({', '.join(sorted(NPU_QUANTS))}) fitting into "
                        f"{free_ram_gb()} GB of free memory")
            if engine == "npu":
                raise SystemExit(f"STOPPED: {msg}")
            say(f"{msg} — running on Ollama ({ollama_host})")
            _STATE.update(engine="ollama", detail=msg, model=ollama_model)
            return ollama_chat()
        r = start_server(model, port=port)
        if not r.get("ok"):
            if engine == "npu":
                raise SystemExit(f"STOPPED: llama-server failed to start: {r.get('error')}")
            say(f"llama-server failed to start ({r.get('error')}) — falling back to Ollama")
            _STATE.update(engine="ollama", detail=r.get("error", ""), model=ollama_model)
            return ollama_chat()
        if not r.get("npu_active"):
            # server is alive but the log has no ggml-hex: llama.cpp quietly
            # fell back to CPU/OpenCL (test-signing? driver?) — no point in
            # keeping it, fall back
            msg = ("NPU not active (no ggml-hex in the log — check test-signing "
                   "and ADSP_LIBRARY_PATH; log: "
                   f"{r.get('log')})")
            stop_server()
            if engine == "npu":
                raise SystemExit(f"STOPPED: {msg}")
            say(f"{msg} — falling back to Ollama")
            _STATE.update(engine="ollama", detail=msg, model=ollama_model)
            return ollama_chat()
        say(f"NPU active: {Path(model).name} ({quant_of(model)}), "
            f"port {port}, log {r.get('log')}")
        _STATE.update(engine="npu", detail="", model=Path(model).name,
                      server_log=r.get("log"))
        return make_openai_chat(f"http://127.0.0.1:{port}", model)
    # engine == ollama
    _STATE.update(engine="ollama", detail="", model=ollama_model)
    return ollama_chat()

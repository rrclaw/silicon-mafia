"""LLM backends. Three interchangeable providers behind one `complete()` call:

1. ClaudeCliBackend     — `claude -p` subprocess (Claude subscription, no key)
2. AnthropicApiBackend  — official anthropic SDK (ANTHROPIC_API_KEY)
3. OpenAICompatBackend  — any /chat/completions endpoint (DeepSeek / GLM / Kimi / ...)

Selection order: MAFIA_PROVIDER env > ANTHROPIC_API_KEY > DEEPSEEK_API_KEY >
GLM_API_KEY > OPENAI_COMPAT_API_KEY > claude CLI fallback.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

log = logging.getLogger("mafia.ai")

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
TIMEOUT_S = 180


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


class Backend:
    name = "base"

    def complete(self, system: str, prompt: str) -> str:
        raise NotImplementedError


class ClaudeCliBackend(Backend):
    name = "claude-cli"

    def __init__(self, binary: str | None = None):
        self.binary = binary or os.environ.get("CLAUDE_BIN") or _find_claude()

    def complete(self, system: str, prompt: str) -> str:
        args = [self.binary, "-p", "--system-prompt", system,
                "--disable-slash-commands", prompt]
        proc = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT_S)
        if proc.returncode != 0:
            raise RuntimeError(f"claude -p failed: {proc.stderr[:500]}")
        return proc.stdout.strip()


def _find_claude() -> str:
    for cand in [os.path.expanduser("~/.local/bin/claude"),
                 "/usr/local/bin/claude", "/opt/homebrew/bin/claude", "claude"]:
        if os.path.exists(cand) or cand == "claude":
            return cand
    return "claude"


class AnthropicApiBackend(Backend):
    name = "anthropic"

    def __init__(self, model: str | None = None):
        import anthropic  # lazy: only needed in API mode
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("MAFIA_MODEL", "claude-sonnet-4-6")

    def complete(self, system: str, prompt: str) -> str:
        resp = self.client.messages.create(
            model=self.model, max_tokens=8192, system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")


class OpenAICompatBackend(Backend):
    """DeepSeek / GLM(智谱) / Kimi / any OpenAI-compatible chat endpoint."""
    name = "openai-compat"

    def __init__(self, base_url: str, api_key: str, model: str):
        import httpx
        self.http = httpx.Client(timeout=TIMEOUT_S)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def complete(self, system: str, prompt: str) -> str:
        r = self.http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "max_tokens": 8192,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": prompt}]},
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


PRESETS = {
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat",
                 "key_env": "DEEPSEEK_API_KEY"},
    "glm": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-plus",
            "key_env": "GLM_API_KEY"},
    "kimi": {"base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-32k",
             "key_env": "KIMI_API_KEY"},
}

_BACKEND: Backend | None = None


def get_backend() -> Backend:
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND
    provider = os.environ.get("MAFIA_PROVIDER", "").lower()
    model = os.environ.get("MAFIA_MODEL")

    if provider in PRESETS:
        p = PRESETS[provider]
        key = os.environ.get(p["key_env"]) or os.environ.get("OPENAI_COMPAT_API_KEY", "")
        _BACKEND = OpenAICompatBackend(p["base_url"], key, model or p["model"])
    elif provider == "anthropic":
        _BACKEND = AnthropicApiBackend(model)
    elif provider in ("openai", "openai_compat", "openai-compat"):
        _BACKEND = OpenAICompatBackend(
            os.environ["OPENAI_COMPAT_BASE_URL"],
            os.environ["OPENAI_COMPAT_API_KEY"],
            model or os.environ.get("OPENAI_COMPAT_MODEL", "gpt-4o"),
        )
    elif provider in ("cli", "claude-cli", "claude_cli"):
        _BACKEND = ClaudeCliBackend()
    elif os.environ.get("ANTHROPIC_API_KEY"):
        _BACKEND = AnthropicApiBackend(model)
    elif os.environ.get("DEEPSEEK_API_KEY"):
        p = PRESETS["deepseek"]
        _BACKEND = OpenAICompatBackend(p["base_url"], os.environ["DEEPSEEK_API_KEY"],
                                       model or p["model"])
    elif os.environ.get("GLM_API_KEY"):
        p = PRESETS["glm"]
        _BACKEND = OpenAICompatBackend(p["base_url"], os.environ["GLM_API_KEY"],
                                       model or p["model"])
    elif os.environ.get("OPENAI_COMPAT_API_KEY"):
        _BACKEND = OpenAICompatBackend(
            os.environ["OPENAI_COMPAT_BASE_URL"],
            os.environ["OPENAI_COMPAT_API_KEY"],
            model or os.environ.get("OPENAI_COMPAT_MODEL", "gpt-4o"),
        )
    else:
        _BACKEND = ClaudeCliBackend()
    log.info("mafia backend: %s", _BACKEND.name)
    return _BACKEND


def call_llm(system: str, prompt: str, label: str) -> dict:
    """One retried call, JSON extracted, fully logged. Raises on double failure."""
    backend = get_backend()
    last_err: Exception | None = None
    for attempt in (1, 2):
        ts = time.time()
        try:
            raw = backend.complete(system, prompt)
            data = extract_json(raw)
            _log_call(label, prompt, raw, time.time() - ts, ok=True)
            return data
        except Exception as e:  # noqa: BLE001 — any failure retries once
            last_err = e
            _log_call(f"{label}_a{attempt}", prompt, repr(e), time.time() - ts, ok=False)
            log.warning("LLM call %s attempt %d failed: %s", label, attempt, e)
    raise RuntimeError(f"LLM call {label} failed twice: {last_err}")


def extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start < 0:
        raise ValueError(f"no JSON in: {text[:200]}")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError(f"unbalanced JSON in: {text[:200]}")


def _log_call(label: str, prompt: str, output: str, elapsed: float, ok: bool) -> None:
    path = LOG_DIR / f"{int(time.time())}_{label}.log"
    try:
        path.write_text(f"[{label}] ok={ok} elapsed={elapsed:.1f}s backend={get_backend().name}\n"
                        f"=== prompt ===\n{prompt}\n=== output ===\n{output}\n")
    except Exception:  # noqa: BLE001
        pass

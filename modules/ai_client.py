"""Klien LLM minimal via REST — tanpa SDK/dependensi tambahan (pakai urllib).

Mendukung free-tier: Google Gemini & Groq. API key dibaca dari environment
variable (lihat .env.example). Semua kegagalan dikembalikan sebagai None agar
pemanggil bisa fallback ke jalur non-AI tanpa menggagalkan pipeline.
"""
import json
import os
import urllib.error
import urllib.request
from typing import Optional

_GEMINI_DEFAULT_MODEL = "gemini-2.0-flash"
_GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_TIMEOUT = 60


def get_api_key(provider: str) -> str:
    """Ambil API key dari env sesuai provider ('' bila belum diset)."""
    env = "GROQ_API_KEY" if (provider or "").lower() == "groq" else "GEMINI_API_KEY"
    return os.environ.get(env, "").strip()


def available(provider: str) -> bool:
    """True bila key untuk provider tersedia."""
    return bool(get_api_key(provider))


def _http_post_json(url: str, payload: dict, headers: dict, timeout: int = _TIMEOUT) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def complete(
    prompt: str,
    provider: str = "gemini",
    system: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> Optional[str]:
    """Kirim prompt ke LLM, kembalikan teks balasan. None bila tak ada key/gagal."""
    provider = (provider or "gemini").lower()
    if not get_api_key(provider):
        return None
    try:
        if provider == "groq":
            return _complete_groq(prompt, system, temperature, max_tokens)
        return _complete_gemini(prompt, system, temperature, max_tokens)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        print(f"[WARNING] AI ({provider}) HTTP {exc.code}: {detail}")
        return None
    except Exception as exc:
        print(f"[WARNING] Panggilan AI ({provider}) gagal: {exc}")
        return None


def _complete_gemini(prompt, system, temperature, max_tokens):
    key = get_api_key("gemini")
    model = os.environ.get("GEMINI_MODEL", _GEMINI_DEFAULT_MODEL).strip() or _GEMINI_DEFAULT_MODEL
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    res = _http_post_json(url, payload, {"Content-Type": "application/json"})
    candidates = res.get("candidates") or []
    if not candidates:
        return None
    parts = candidates[0].get("content", {}).get("parts", []) or []
    text = "".join(p.get("text", "") for p in parts).strip()
    return text or None


def _complete_groq(prompt, system, temperature, max_tokens):
    key = get_api_key("groq")
    model = os.environ.get("GROQ_MODEL", _GROQ_DEFAULT_MODEL).strip() or _GROQ_DEFAULT_MODEL
    url = "https://api.groq.com/openai/v1/chat/completions"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    res = _http_post_json(url, payload, headers)
    choices = res.get("choices") or []
    if not choices:
        return None
    return (choices[0].get("message", {}).get("content") or "").strip() or None

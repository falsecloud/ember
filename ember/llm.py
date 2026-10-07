import json

import httpx


def stream_chat(cfg, messages):
    payload = {
        "model": "local",
        "messages": messages,
        "stream": True,
        "temperature": 0.2,
        "top_p": 0.9,
        "cache_prompt": True,  # reuse the KV cache of earlier turns -> near-instant follow-ups
        "max_tokens": int(cfg.get("max_tokens", 3072)),
    }
    url = f"http://127.0.0.1:{cfg['port']}/v1/chat/completions"
    with httpx.stream("POST", url, json=payload, timeout=None) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            d = line[5:].strip()
            if d == "[DONE]":
                break
            try:
                delta = json.loads(d)["choices"][0]["delta"].get("content")
            except Exception:
                continue
            if delta:
                yield delta

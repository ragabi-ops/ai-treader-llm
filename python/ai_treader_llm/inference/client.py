import json
from urllib.request import Request, urlopen


def smoke(base_url: str, model: str, timeout: float = 120) -> dict:
    url = base_url.rstrip("/")
    with urlopen(url + "/health", timeout=timeout) as response:
        health = json.load(response)
    request = Request(
        url + "/v1/chat/completions",
        data=json.dumps({"model": model, "messages": [{"role": "user", "content": "Reply with READY."}],
                         "max_tokens": 32}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    content = result["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("endpoint returned no completion text")
    return {"health": health, "model": result.get("model"), "content": content,
            "usage": result.get("usage")}

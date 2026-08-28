"""Resolve a named provider profile from config and call its chat/completions endpoint."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

MAX_RATE_LIMIT_RETRIES = 5
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 10


class ProviderError(RuntimeError):
    pass


def resolve_provider(config: dict, stage: str) -> dict:
    stage_config = config.get(stage) or {}
    provider_name = stage_config.get("activeProvider")
    if not provider_name:
        raise ProviderError(f"{stage}.activeProvider is not set")
    providers = config.get("providers") or {}
    provider = providers.get(provider_name)
    if not provider:
        raise ProviderError(f"providers.{provider_name} is not defined")
    return {
        "name": provider_name,
        "endpoint": provider["endpoint"],
        "model": provider["model"],
        "api_key": os.environ.get(provider.get("apiKeyEnv", "")) if provider.get("apiKeyEnv") else None,
        "extra_headers": provider.get("headers") or {},
        "proxy": provider.get("proxy"),
    }


def _parse_retry_after(error: urllib.error.HTTPError, attempt: int) -> float:
    header = error.headers.get("Retry-After") if error.headers else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    return DEFAULT_RATE_LIMIT_BACKOFF_SECONDS * (2**attempt)


def call_chat_completions(provider: dict, messages: list[dict], temperature: float = 0.2, timeout: int = 600) -> str:
    body = {"model": provider["model"], "temperature": temperature, "messages": messages}
    headers = {"Content-Type": "application/json", **provider.get("extra_headers", {})}
    if provider.get("api_key"):
        headers["Authorization"] = f"Bearer {provider['api_key']}"
    request_body = json.dumps(body).encode("utf-8")

    opener = urllib.request.urlopen
    proxy_url = provider.get("proxy")
    if proxy_url:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})).open

    attempt = 0
    while True:
        request = urllib.request.Request(provider["endpoint"], data=request_body, headers=headers, method="POST")
        try:
            with opener(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
                time.sleep(_parse_retry_after(error, attempt))
                attempt += 1
                continue
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise ProviderError(f"{provider['name']}: HTTP {error.code} — {detail}") from error
        except urllib.error.URLError as error:
            raise ProviderError(f"{provider['name']}: {error.reason}") from error

    content = payload["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content)

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
    api_key_env = provider.get("apiKeyEnv")
    env_names = api_key_env if isinstance(api_key_env, list) else ([api_key_env] if api_key_env else [])
    api_keys = [os.environ[name] for name in env_names if os.environ.get(name)]
    return {
        "name": provider_name,
        "endpoint": provider["endpoint"],
        "model": provider["model"],
        "api_keys": api_keys,
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
    base_headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; jarvis-activity-journal/1.0)",
        **provider.get("extra_headers", {}),
    }
    request_body = json.dumps(body).encode("utf-8")

    opener = urllib.request.urlopen
    proxy_url = provider.get("proxy")
    if proxy_url:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})).open

    keys = provider.get("api_keys") or [None]
    max_attempts = MAX_RATE_LIMIT_RETRIES * len(keys)
    attempt = 0
    while True:
        key = keys[attempt % len(keys)]
        headers = dict(base_headers)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        request = urllib.request.Request(provider["endpoint"], data=request_body, headers=headers, method="POST")
        try:
            with opener(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < max_attempts:
                attempt += 1
                if len(keys) > 1 and attempt % len(keys) != 0:
                    continue
                time.sleep(_parse_retry_after(error, attempt // len(keys)))
                continue
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise ProviderError(f"{provider['name']}: HTTP {error.code} — {detail}") from error
        except urllib.error.URLError as error:
            raise ProviderError(f"{provider['name']}: {error.reason}") from error

    content = payload["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content)

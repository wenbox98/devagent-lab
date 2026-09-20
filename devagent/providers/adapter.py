"""Minimal OpenAI-compatible HTTP adapter using only the Python standard library."""
from __future__ import annotations

from collections.abc import Mapping
import json
import socket
from typing import Any
from urllib import error, request

from ..config import ProviderConfig, load_provider_config
from ..models import ModelRequest, ModelResponse


class ProviderError(Exception):
    """Base class for expected failures at the provider boundary."""


class ProviderAuthenticationError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    pass


class ProviderTimeoutError(ProviderError):
    pass


class ProviderResponseError(ProviderError):
    pass


class ProviderServiceError(ProviderError):
    pass


def _optional_usage(raw: Mapping[str, Any], name: str) -> int | None:
    usage = raw.get("usage")
    if usage is None:
        return None
    if not isinstance(usage, Mapping):
        raise ProviderResponseError("provider usage must be an object when present")
    value = usage.get(name)
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ProviderResponseError(f"provider usage.{name} must be a non-negative integer")
    return value


def unwrap_response(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    if "response" in raw:
        response = raw["response"]
        if not isinstance(response, Mapping):
            raise ProviderResponseError("provider response wrapper must contain an object")
        return response
    return raw


def normalize_response(raw: Mapping[str, Any], config: ProviderConfig) -> ModelResponse:
    raw = unwrap_response(raw)
    try:
        choices = raw["choices"]
        text = choices[0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderResponseError("provider response is missing choices[0].message.content") from exc
    if not isinstance(text, str):
        raise ProviderResponseError("provider response content must be text")
    returned_model = raw.get("model")
    if returned_model is not None and not isinstance(returned_model, str):
        raise ProviderResponseError("provider response model must be text when present")
    return ModelResponse(
        text=text,
        provider=config.provider,
        model=returned_model or config.model,
        input_tokens=_optional_usage(raw, "prompt_tokens"),
        output_tokens=_optional_usage(raw, "completion_tokens"),
    )


class UrllibJsonTransport:
    """Perform one JSON POST. It has no retry loop."""

    def post_json(self, url: str, headers: Mapping[str, str], payload: Mapping[str, Any], timeout: float) -> Mapping[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        outgoing = request.Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with request.urlopen(outgoing, timeout=timeout) as response:
                raw_body = response.read()
        except error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise ProviderAuthenticationError("provider rejected credentials") from exc
            if exc.code == 429:
                raise ProviderRateLimitError("provider rate limit exceeded") from exc
            raise ProviderServiceError(f"provider HTTP status {exc.code}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ProviderTimeoutError("provider request timed out") from exc
        except error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise ProviderTimeoutError("provider request timed out") from exc
            raise ProviderServiceError("provider network request failed") from exc
        try:
            decoded = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderResponseError("provider returned invalid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise ProviderResponseError("provider JSON root must be an object")
        return decoded


class OpenAICompatibleAdapter:
    """Translate generic domain objects to/from an OpenAI-compatible chat API."""

    def __init__(self, *, config: ProviderConfig | None = None,
                 environ: Mapping[str, str] | None = None, transport=None):
        self._config = config
        self._environ = environ
        self._transport = transport or UrllibJsonTransport()
        self.call_count = 0

    def complete(self, model_request: ModelRequest) -> ModelResponse:
        config = self._config or load_provider_config(self._environ)
        endpoint = config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": "Bearer " + config.api_key, "Content-Type": "application/json"}
        payload = {"model": config.model, "messages": [{"role": "user", "content": model_request.task}]}
        self.call_count += 1
        try:
            raw = self._transport.post_json(endpoint, headers, payload, config.timeout_seconds)
        except (ProviderAuthenticationError, ProviderRateLimitError, ProviderTimeoutError,
                ProviderResponseError, ProviderServiceError):
            raise
        except TimeoutError as exc:
            raise ProviderTimeoutError("provider request timed out") from exc
        return normalize_response(raw, config)

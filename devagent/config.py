"""Read real-provider settings without storing credentials in the repository."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
import platform


class ConfigMissingError(Exception):
    """Required real-provider configuration is absent or invalid."""


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    api_key: str = field(repr=False)
    base_url: str
    timeout_seconds: float = 30.0
    client_version: str = field(default_factory=lambda: f"stdlib-urllib/python-{platform.python_version()}")


def load_provider_config(environ: Mapping[str, str] | None = None) -> ProviderConfig:
    values = os.environ if environ is None else environ
    names = {
        "provider": "DEVAGENT_PROVIDER",
        "model": "DEVAGENT_MODEL",
        "api_key": "DEVAGENT_API_KEY",
        "base_url": "DEVAGENT_API_BASE_URL",
    }
    loaded = {field: values.get(name, "").strip() for field, name in names.items()}
    missing = [name for field, name in names.items() if not loaded[field]]
    if missing:
        raise ConfigMissingError("missing configuration: " + ", ".join(missing))
    try:
        timeout = float(values.get("DEVAGENT_TIMEOUT_SECONDS", "30"))
    except ValueError as exc:
        raise ConfigMissingError("DEVAGENT_TIMEOUT_SECONDS must be a positive number") from exc
    if timeout <= 0:
        raise ConfigMissingError("DEVAGENT_TIMEOUT_SECONDS must be a positive number")
    return ProviderConfig(timeout_seconds=timeout, **loaded)

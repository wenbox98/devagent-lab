"""Provider-specific code is isolated behind the domain ModelRequest/ModelResponse contract."""

from .adapter import OpenAICompatibleAdapter

__all__ = ["OpenAICompatibleAdapter"]

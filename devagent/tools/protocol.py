"""Domain tool messages: proposals are not execution results."""
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: Any  # Untrusted until the executor validates it.


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    ok: bool
    data: Any = None
    error: ToolError | None = None

    def __post_init__(self):
        if type(self.ok) is not bool or self.ok == (self.error is not None):
            raise ValueError('success must have no error; failure must have an error')
        if not self.ok and self.data is not None:
            raise ValueError('failed tools must not return success data')

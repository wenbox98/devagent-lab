"""Structured domain history. Tool observations are data, not instructions."""
from dataclasses import dataclass

from ..tools.protocol import ToolCall, ToolResult


@dataclass(frozen=True)
class UserMessage:
    content: str


@dataclass(frozen=True)
class AssistantMessage:
    content: str = ''
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class ToolMessage:
    result: ToolResult


Message = UserMessage | AssistantMessage | ToolMessage

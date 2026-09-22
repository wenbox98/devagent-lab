"""可重复的教学客户端，不调用网络或付费 API。"""
from .models import ModelRequest, ModelResponse
from .tools.protocol import ToolCall


class FakeModelClient:
    def __init__(self, mode: str = "success"):
        if mode not in {"success", "timeout", "bad_response", "tool_call"}:
            raise ValueError("unknown fake model mode")
        self.mode = mode
        self.call_count = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.call_count += 1
        if self.mode == "timeout":
            raise TimeoutError("simulated timeout")
        if self.mode == "tool_call":
            return ModelResponse(text='', provider='fake', tool_calls=(
                ToolCall('c1', 'read_file', {'path': 'pagination.py', 'end_line': 3}),))
        text = "" if self.mode == "bad_response" else "【模拟输出】" + request.task
        return ModelResponse(text=text, provider="fake")

"""机制实验：工具注册表、两层校验、ID关联。无eval、无网络。
本实验的读取器仅用于自己创建且无并发修改的临时目录，不替代项目L02。
"""
from dataclasses import dataclass, asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import json

@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict

@dataclass(frozen=True)
class ToolResult:
    call_id: str
    status: str
    content: str | None = None
    error_code: str | None = None

def dispatcher(root, call):
    if call.name != "read_file":
        return ToolResult(call.call_id, "failed", error_code="unknown_tool")
    if set(call.arguments) != {"path"} or not isinstance(call.arguments["path"], str):
        return ToolResult(call.call_id, "failed", error_code="invalid_arguments")
    target = (root / call.arguments["path"]).resolve()
    if not target.is_relative_to(root):
        return ToolResult(call.call_id, "failed", error_code="permission_denied")
    with target.open("rb") as stream:
        data = stream.read(1025)
    if len(data) > 1024:
        return ToolResult(call.call_id, "failed", error_code="too_large")
    return ToolResult(call.call_id, "succeeded", content=data.decode("utf-8"))

def main():
    with TemporaryDirectory(prefix="devagent-tool-") as directory:
        root = Path(directory).resolve()
        (root / "a.py").write_bytes(b"answer = 42\n")
        calls = [ToolCall("c1", "read_file", {"path":"a.py"}),
                 ToolCall("c2", "read_file", {"path":"../outside.py"}),
                 ToolCall("c3", "unknown", {})]
        results = [dispatcher(root, call) for call in calls]
        assert [r.call_id for r in results] == ["c1", "c2", "c3"]
        assert results[0].content == "answer = 42\n"
        assert results[1].error_code == "permission_denied"
        assert results[2].error_code == "unknown_tool"
        print(json.dumps({"scope":"controlled-tool-protocol", "results":[asdict(r) for r in results],
                          "verified":True}, ensure_ascii=True))

if __name__ == "__main__":
    main()

"""标准库工具协议教学；资料在内存fixture中，不是实际仓库。"""
import json

FIXTURE = {"src/page.py": "def page(items): return items"}

def execute(call: dict, allowed: set[str]) -> dict:
    if call["name"] not in allowed:
        return {"tool_call_id": call["id"], "error": "unauthorized"}
    path = call["args"].get("path")
    if path not in FIXTURE:
        return {"tool_call_id": call["id"], "error": "path_denied"}
    return {"tool_call_id": call["id"], "content": FIXTURE[path]}

def main() -> None:
    call = {"id": "call-1", "name": "read_fixture", "args": {"path": "src/page.py"}}
    result = execute(call, {"read_fixture"})
    assert result["tool_call_id"] == call["id"]
    print(json.dumps(result, sort_keys=True))
    denied = execute(call, set())
    assert denied["error"] == "unauthorized"
    print(denied["error"])

if __name__ == "__main__":
    main()

"""可见反馈循环：脚本模型提出工具，读取真实临时文件，再根据ToolResult回答。
这不是大模型智能效果验证，不改主项目、不执行仓库代码、不请求网络。
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import json

class ScriptedModel:
    def __init__(self):
        self.calls = 0
    def complete(self, messages):
        self.calls += 1
        observations = [m for m in messages if m["role"] == "tool"]
        if not observations:
            return {"kind":"tool", "call_id":"read-1", "name":"read_file", "path":"page.py"}
        last = observations[-1]
        assert last["call_id"] == "read-1"
        # 答案包含真实读取结果，不从预设expected答案填充。
        return {"kind":"final", "text":"Observed source: " + last["content"].strip()}

def read_controlled(root, relative):
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise PermissionError("outside controlled workspace")
    with target.open("rb") as stream:
        raw = stream.read(1025)
    if len(raw) > 1024:
        raise ValueError("teaching file too large")
    return raw.decode("utf-8")

def run(root, model, max_rounds=3):
    messages = [{"role":"user", "content":"Read the pagination implementation."}]
    events = []
    for turn in range(max_rounds):
        answer = model.complete(messages)
        events.append({"turn":turn + 1, "model_kind":answer["kind"]})
        if answer["kind"] == "final":
            return answer["text"], messages, events
        if answer["kind"] != "tool" or answer["name"] != "read_file":
            raise ValueError("unsupported teaching response")
        messages.append({"role":"assistant", **answer})
        content = read_controlled(root, answer["path"])
        messages.append({"role":"tool", "call_id":answer["call_id"], "content":content})
        events.append({"tool":"read_file", "call_id":answer["call_id"], "observed":content})
    return "budget_exhausted", messages, events

def main():
    with TemporaryDirectory(prefix="devagent-loop-") as directory:
        root = Path(directory).resolve()
        text = "start = page_no * size\n"
        (root / "page.py").write_bytes(text.encode("utf-8"))
        model = ScriptedModel()
        answer, messages, events = run(root, model)
        assert model.calls == 2
        assert text.strip() in answer
        assert len([m for m in messages if m["role"] == "tool"]) == 1
        print(json.dumps({"scope":"scripted-model-real-temp-read", "model_calls":model.calls,
                          "events":events, "answer":answer, "verified":True}, ensure_ascii=True))

if __name__ == "__main__":
    main()

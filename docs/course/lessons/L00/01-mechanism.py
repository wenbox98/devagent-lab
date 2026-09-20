"""机制实验：输入拒绝必须发生在下游调用前。仅标准库、无模型请求。"""
from dataclasses import dataclass
import json

@dataclass
class Result:
    status: str
    error_code: str | None

class Client:
    def __init__(self, reply="answer"):
        self.reply = reply
        self.calls = 0
    def complete(self, task):
        self.calls += 1
        return self.reply

def handle(task, client):
    if not isinstance(task, str) or not task.strip():
        return Result("failed", "invalid_input")
    text = client.complete(task.strip())
    if not isinstance(text, str) or not text.strip():
        return Result("failed", "invalid_response")
    return Result("succeeded", None)

def main():
    rejected = Client()
    assert handle("  ", rejected).error_code == "invalid_input"
    assert rejected.calls == 0
    empty = Client("")
    assert handle("question", empty).error_code == "invalid_response"
    assert empty.calls == 1
    print(json.dumps({"scope":"teaching-only", "invalid_input_calls":rejected.calls,
                      "empty_response_calls":empty.calls, "verified":True}))

if __name__ == "__main__":
    main()

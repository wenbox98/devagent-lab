"""机制实验：副作用已发生但记录仍unknown，按前后hash对账。
效果仅为受控临时文件，不模拟所有外部API的幂等。
"""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json

def h(data):
    return sha256(data).hexdigest()

def reconcile(record, current):
    value = h(current)
    if value == record["after_hash"]:
        return "applied"
    if value == record["before_hash"]:
        return "not_observed_yet"
    return "needs_review"

def main():
    with TemporaryDirectory(prefix="devagent-reconcile-") as directory:
        path = Path(directory) / "file.txt"
        before, after = b"before", b"after"
        record = {"operation_id":"op1", "state":"unknown",
                  "before_hash":h(before), "after_hash":h(after)}
        path.write_bytes(after)  # 模拟效果已落盘但成功记录尚未更新。
        assert reconcile(record, path.read_bytes()) == "applied"
        path.write_bytes(b"someone else's version")
        assert reconcile(record, path.read_bytes()) == "needs_review"
        assert reconcile(record, before) == "not_observed_yet"
        print(json.dumps({"scope":"hash-reconciliation-only", "applied_detected":True,
                          "foreign_version":"needs_review", "verified":True}))

if __name__ == "__main__":
    main()

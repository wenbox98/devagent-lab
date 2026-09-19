"""结构校验与事实校验是不同层；所有证据均为显式教学fixture。"""
def validate(payload: dict, evidence: dict, task_id: str) -> str:
    if payload.get("status") not in {"succeeded", "failed"}:
        return "schema_error"
    ids = payload.get("evidence_ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        return "schema_error"
    if any(i not in evidence for i in ids):
        return "missing_evidence"
    if any(evidence[i]["task_id"] != task_id for i in ids):
        return "wrong_task"
    if payload["status"] == "succeeded" and not all(evidence[i]["passed"] for i in ids):
        return "not_verified"
    return "verified_fixture"

def main() -> None:
    evidence = {"e1": {"task_id": "t1", "passed": True}}
    cases = [({}, "schema_error"),
             ({"status": "succeeded", "evidence_ids": ["fake"]}, "missing_evidence"),
             ({"status": "succeeded", "evidence_ids": ["e1"]}, "verified_fixture")]
    for payload, expected in cases:
        actual = validate(payload, evidence, "t1")
        assert actual == expected
        print(actual)
    # 实际项目还必须核对owner、代码版本、测试数量和禁止修改范围。

if __name__ == "__main__":
    main()

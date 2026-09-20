"""机制实验：字符预算装配，不冒充token计数；硬约束不能被摘要替换。"""
import json

def assemble(required, optional, max_chars):
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("invalid character budget")
    hard = "\n".join(required)
    if len(hard) > max_chars:
        raise ValueError("required_context_exceeds_budget")
    result = hard
    included = []
    for evidence in optional:
        candidate = result + "\n" + evidence
        if len(candidate) <= max_chars:
            result = candidate
            included.append(evidence)
    return result, included

def main():
    required = ["Only workspace A", "Do not edit tests"]
    result, included = assemble(required, ["short", "x" * 1000], 80)
    assert all(item in result for item in required)
    assert included == ["short"]
    assert len(result) <= 80
    rejected = False
    try:
        assemble(required, [], 2)
    except ValueError:
        rejected = True
    assert rejected
    print(json.dumps({"scope":"character-budget-not-tokens", "required_preserved":True,
                      "optional_kept":included, "verified":True}))

if __name__ == "__main__":
    main()

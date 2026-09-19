"""用标准库手推reducer，非LangGraph运行结果。"""
def merge(state: dict, update: dict) -> dict:
    out = dict(state)
    for key, value in update.items():
        out[key] = state.get(key, []) + value if key == "evidence" else value
    return out

def main() -> None:
    initial = {"budget": 2, "evidence": ["read:v1"]}
    good = merge(initial, {"budget": 1, "evidence": ["test:failed"]})
    bad = merge(initial, {"evidence": ["read:v1", "test:failed"]})
    assert good["evidence"] == ["read:v1", "test:failed"]
    assert bad["evidence"].count("read:v1") == 2
    assert initial["budget"] == 2
    print("delta:", good)
    print("full-history mistake:", bad)

if __name__ == "__main__":
    main()

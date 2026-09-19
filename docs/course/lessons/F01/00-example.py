"""标准库数据流教学；没有导入LangChain，不是框架运行验证。"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Reply:
    text: str
    provider: str

def normalize(task: str) -> dict[str, str]:
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a nonempty string")
    return {"role": "user", "content": task.strip()}

def scripted_model(message: dict[str, str]) -> Reply:
    return Reply("fixture: " + message["content"], "scripted")

def main() -> None:
    message = normalize(" explain pagination ")
    response = scripted_model(message)
    assert message["role"] == "user"
    assert response.provider == "scripted"
    print(message)
    print(response.text)
    try:
        normalize(42)  # 故意传错类型，验证运行时边界
    except ValueError:
        print("type_error: rejected before model")
    else:
        raise AssertionError("wrong input was accepted")

if __name__ == "__main__":
    main()

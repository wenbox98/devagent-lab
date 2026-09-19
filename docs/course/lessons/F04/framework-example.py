"""纯函数LangGraph示例；节点名与状态键有意不同。v4运行状态见validation/report.md。"""
from operator import add
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END

class State(TypedDict):
    remaining: int
    evidence: Annotated[list[str], add]
    passed: bool

def inspect_node(state: State):
    return {"evidence": ["read:v1"]}

def verify_node(state: State):
    left = state["remaining"] - 1
    return {"remaining": left, "passed": left == 0, "evidence": ["verify:" + str(left)]}

def route(state: State):
    return "finish" if state["passed"] or state["remaining"] <= 0 else "retry"

def build_graph():
    builder = StateGraph(State)
    builder.add_node("inspect", inspect_node)
    builder.add_node("verify", verify_node)
    builder.add_edge(START, "inspect")
    builder.add_edge("inspect", "verify")
    builder.add_conditional_edges("verify", route, {"finish": END, "retry": "verify"})
    return builder.compile()

def main():
    result = build_graph().invoke({"remaining": 2, "evidence": [], "passed": False})
    assert result["evidence"] == ["read:v1", "verify:1", "verify:0"]
    print(result)

if __name__ == "__main__":
    main()

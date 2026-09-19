"""interrupt/Command同进程示例；不是持久审批或真实身份系统。v4运行状态见validation/report.md。"""
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command

class State(TypedDict):
    proposal_hash: str
    approved: bool

def review(state: State):
    decision = interrupt({"proposal_hash": state["proposal_hash"], "action": "teaching-only"})
    ok = (isinstance(decision, dict) and decision.get("approved") is True
          and decision.get("proposal_hash") == state["proposal_hash"])
    return {"approved": ok}

def main():
    builder = StateGraph(State)
    builder.add_node("review_node", review)
    builder.add_edge(START, "review_node")
    builder.add_edge("review_node", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "teaching-approval"}}
    paused = graph.invoke({"proposal_hash": "p1", "approved": False}, config)
    assert paused.get("__interrupt__")
    print("waiting_for_approval: true")
    result = graph.invoke(Command(resume={"approved": True, "proposal_hash": "p1"}), config)
    assert result["approved"]
    print("approved:", result["approved"])
    print("external_effects: none")

if __name__ == "__main__":
    main()

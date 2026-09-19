"""跨命令LangGraph检查点演示。先start，再以相同目录resume。v4运行状态见validation/report.md。"""
import argparse
import os
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
from pathlib import Path
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

class State(TypedDict):
    planned: bool
    complete: bool

def make_builder(fail: bool):
    builder = StateGraph(State)
    def plan(state: State):
        return {"planned": True}
    def finish(state: State):
        if fail:
            raise RuntimeError("simulated_node_failure_after_plan")
        return {"complete": True}
    builder.add_node("plan_node", plan)
    builder.add_node("finish_node", finish)
    builder.add_edge(START, "plan_node")
    builder.add_edge("plan_node", "finish_node")
    builder.add_edge("finish_node", END)
    return builder

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["start", "resume"])
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    db = args.directory / "checkpoint.sqlite"
    if args.phase == "start" and db.exists():
        parser.error("start requires a fresh directory; existing checkpoint will not be overwritten")
    if args.phase == "resume" and not db.exists():
        parser.error("checkpoint missing: run start first")
    config = {"configurable": {"thread_id": "teaching-task-1"}}
    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = make_builder(args.phase == "start").compile(checkpointer=saver)
        if args.phase == "start":
            try:
                graph.invoke({"planned": False, "complete": False}, config)
            except RuntimeError as exc:
                print(str(exc))
                print("checkpoint_planned:", graph.get_state(config).values.get("planned"))
                print("task_complete: false")
            else:
                raise AssertionError("expected simulated failure")
        else:
            result = graph.invoke(None, config)
            assert result["planned"] and result["complete"]
            print("task_complete:", result["complete"])
    # 这里只验证图恢复；外部副作用幂等必须由课程实现另行验证。

if __name__ == "__main__":
    main()

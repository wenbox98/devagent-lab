"""真实middleware接口例子；无API调用。v4运行状态见validation/report.md。"""
import importlib.util
import json
from pathlib import Path
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage
from pydantic import BaseModel, ValidationError

class ClaimedResult(BaseModel):
    status: str
    evidence_ids: list[str]

@wrap_tool_call
def deny_teaching_tool(request, handler):
    # 这里故意拒绝唯一工具，演示拒绝时不调用handler；不是完整授权系统。
    return ToolMessage(content=json.dumps({"error": "unauthorized"}), tool_call_id=request.tool_call["id"])

def main():
    path = Path(__file__).resolve().parents[1] / "F02" / "framework-example.py"
    spec = importlib.util.spec_from_file_location("course_f02", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    agent = create_agent(model=module.ScriptedModel(), tools=[module.read_fixture], middleware=[deny_teaching_tool])
    result = agent.invoke({"messages": [{"role": "user", "content": "read fixture"}]}, config={"recursion_limit": 10})
    outputs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert json.loads(outputs[0].content)["error"] == "unauthorized"
    payload = ClaimedResult.model_validate({"status": "succeeded", "evidence_ids": ["nonexistent"]})
    print("schema_valid:", payload.status)
    print("business_verified: false; referenced evidence does not exist")
    # 脚本模型仍然可能宣称完成：这正说明业务状态不能采用模型自述。
    print("tool_execution: denied")

if __name__ == "__main__":
    main()

"""真实create_agent，脚本模型与内存工具；不验证真实模型选择质量。"""
from typing import Any
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

@tool
def read_fixture(path: str) -> str:
    """Read the single in-memory teaching file src/page.py; other paths are denied."""
    if path != "src/page.py":
        return "path_denied"
    return "def page(items): return items"

class ScriptedModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "course-scripted-model"

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any):
        # 教学stub只负责固定协议响应；不是供应商能力实现。
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(isinstance(message, ToolMessage) for message in messages):
            response = AIMessage(content="fixture read completed")
        else:
            response = AIMessage(content="", tool_calls=[{
                "name": "read_fixture", "args": {"path": "src/page.py"},
                "id": "call-1", "type": "tool_call"
            }])
        return ChatResult(generations=[ChatGeneration(message=response)])

def main():
    agent = create_agent(model=ScriptedModel(), tools=[read_fixture], system_prompt="Use only the teaching fixture.")
    result = agent.invoke({"messages": [{"role": "user", "content": "read src/page.py"}]}, config={"recursion_limit": 10})
    tools = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert len(tools) == 1 and tools[0].tool_call_id == "call-1"
    print(result["messages"][-1].content)
    print("tool_call_id:", tools[0].tool_call_id)

if __name__ == "__main__":
    main()

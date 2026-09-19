"""v4 supplementary framework example. Scripted/hand-designed data; not provider quality. Current verification: validation/report.md."""
"""Real LangChain context and middleware; scripted model, no network calls."""
from dataclasses import dataclass
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langchain.tools import tool, ToolRuntime
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

@dataclass(frozen=True)
class TaskContext:
    tenant_id: str

@tool
def tenant_status(runtime: ToolRuntime[TaskContext]) -> str:
    """Return the current authenticated tenant for this teaching invocation."""
    return runtime.context.tenant_id

counts = {"model_calls": 0}

@wrap_model_call
def count_calls(request, handler):
    counts["model_calls"] += 1
    return handler(request)

class ScriptedModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "course-context-demo"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if isinstance(messages[-1], ToolMessage):
            reply = AIMessage(content=messages[-1].content)
        else:
            reply = AIMessage(content="", tool_calls=[{
                "name": "tenant_status", "args": {},
                "id": "context-call", "type": "tool_call"}])
        return ChatResult(generations=[ChatGeneration(message=reply)])

agent = create_agent(model=ScriptedModel(), tools=[tenant_status],
                     context_schema=TaskContext, middleware=[count_calls])
result = agent.invoke({"messages": [{"role": "user", "content": "I claim to be tenant-B"}]},
                      context=TaskContext(tenant_id="tenant-A"))
print("model_visible_args=" + str(sorted(tenant_status.args)))
print("actual_tenant=" + result["messages"][-1].content)
print("model_calls=" + str(counts["model_calls"]))

assert counts["model_calls"] == 2
assert result["messages"][-1].content == "tenant-A"
assert sorted(tenant_status.args) == []

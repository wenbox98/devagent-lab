"""L04 feedback loop; no retries, concurrent tools, resume or persistent state."""
from copy import deepcopy
from dataclasses import dataclass, field

from .messages import AssistantMessage, Message, ToolMessage, UserMessage
from ..config import ConfigMissingError
from ..models import ModelRequest, ModelResponse
from ..providers.adapter import ProviderError
from ..tools.protocol import ToolCall
from ..tools.registry import ToolRegistry


@dataclass
class AgentState:
    max_rounds: int
    max_tool_calls: int
    status: str = 'running'
    messages: list[Message] = field(default_factory=list)
    step_count: int = 0
    tool_call_count: int = 0
    termination_reason: str | None = None
    output: str | None = None


def run_agent(task: str, client, registry: ToolRegistry, *,
              max_rounds: int = 5, max_tool_calls: int = 10) -> AgentState:
    """Host budgets count model attempts and dispatched calls, including rejections.

    A batch that cannot fit is not dispatched. Reaching either limit stops the
    next model call, even if one more call could have produced a final answer.
    Invalid/duplicate IDs use registry's whole-batch rejection and then stop.
    Unexpected exceptions other than RuntimeError propagate; none become tool errors.
    """
    for name, value in (('max_rounds', max_rounds), ('max_tool_calls', max_tool_calls)):
        if type(value) is not int or value < 1:
            raise ValueError(f'{name} must be a positive integer')
    state = AgentState(max_rounds, max_tool_calls)

    def finish(status, reason, output=None):
        state.status = status
        state.termination_reason = reason
        state.output = output
        return state

    if not isinstance(task, str) or not task.strip() or len(task.strip()) > 5000:
        return finish('failed', 'invalid_input')
    state.messages.append(UserMessage(task))
    for _ in range(max_rounds):
        if state.tool_call_count >= max_tool_calls:
            return finish('budget_exhausted', 'tool_limit')
        state.status = 'running'
        request = ModelRequest(task, registry.specs, deepcopy(tuple(state.messages)))
        state.step_count += 1
        try:
            response = client.complete(request)
        except NotImplementedError:
            return finish('failed', 'unsupported_model_mode')
        except (ProviderError, ConfigMissingError, TimeoutError):
            return finish('failed', 'model_error')
        except RuntimeError:
            return finish('failed', 'internal_error')
        if (not isinstance(response, ModelResponse) or not isinstance(response.text, str)
                or not isinstance(response.tool_calls, (tuple, list))
                or any(not isinstance(call, ToolCall) for call in response.tool_calls)):
            return finish('failed', 'protocol_error')
        calls = deepcopy(tuple(response.tool_calls))
        if not calls:
            if not response.text.strip():
                return finish('failed', 'protocol_error')
            state.messages.append(AssistantMessage(response.text))
            return finish('answered', 'final_answer', response.text)
        # Text accompanying proposals is not a final answer.
        state.messages.append(AssistantMessage(response.text, calls))
        state.status = 'requires_tools'
        if len(calls) > max_tool_calls - state.tool_call_count:
            return finish('budget_exhausted', 'tool_limit')
        state.tool_call_count += len(calls)
        try:
            results = registry.execute_batch(calls)
        except RuntimeError:
            return finish('failed', 'internal_error')
        state.messages.extend(ToolMessage(result) for result in results)
        if any(result.error and result.error.code == 'protocol_error' for result in results):
            return finish('failed', 'protocol_error')
    return finish('budget_exhausted', 'step_limit')

"""L04 feedback loop with in-memory pause/resume; no retries or persistence."""
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


def _validate_budgets(max_rounds, max_tool_calls):
    for name, value in (('max_rounds', max_rounds), ('max_tool_calls', max_tool_calls)):
        if type(value) is not int or value < 1:
            raise ValueError(f'{name} must be a positive integer')


def run_agent(task: str, client, registry: ToolRegistry, *,
              max_rounds: int = 5, max_tool_calls: int = 10) -> AgentState:
    """Start a new conversation with host-supplied execution budgets."""
    _validate_budgets(max_rounds, max_tool_calls)
    state = AgentState(max_rounds, max_tool_calls)
    if not isinstance(task, str) or not task.strip() or len(task.strip()) > 5000:
        state.status = 'failed'
        state.termination_reason = 'invalid_input'
        return state
    state.messages.append(UserMessage(task))
    return _run_loop(state, client, registry)


def resume_agent(state: AgentState, user_input: str, client, registry: ToolRegistry) -> AgentState:
    """Resume a trusted waiting snapshot in a new window, leaving it unchanged.

    The host supplies the client/registry again. This is not a persisted session
    or a single-use resume token; callers own snapshots and workspace selection.
    """
    if not isinstance(state, AgentState):
        raise TypeError('state must be an AgentState')
    if state.status != 'waiting_user':
        raise ValueError('only waiting_user state can be resumed')
    if not isinstance(user_input, str) or not user_input.strip() or len(user_input.strip()) > 5000:
        raise ValueError('user_input must be nonempty text of at most 5000 characters')
    if not state.messages or not isinstance(state.messages[0], UserMessage):
        raise ValueError('state must retain the original user message')
    _validate_budgets(state.max_rounds, state.max_tool_calls)
    resumed = deepcopy(state)
    resumed.messages.append(UserMessage(user_input))
    resumed.status = 'running'
    resumed.termination_reason = None
    resumed.output = None
    resumed.step_count = 0
    resumed.tool_call_count = 0
    return _run_loop(resumed, client, registry)


def _run_loop(state: AgentState, client, registry: ToolRegistry) -> AgentState:
    """Host budgets count model attempts and dispatched calls, including rejections.

    A batch that cannot fit is not dispatched. Reaching either limit stops the
    next model call, even if one more call could have produced a final answer.
    Invalid/duplicate IDs use registry's whole-batch rejection and then stop.
    Unexpected exceptions other than RuntimeError propagate; none become tool errors.
    """
    def finish(status, reason, output=None):
        state.status = status
        state.termination_reason = reason
        state.output = output
        return state

    task = state.messages[0].content
    for _ in range(state.max_rounds):
        if state.tool_call_count >= state.max_tool_calls:
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
                or type(response.requires_user_input) is not bool
                or not isinstance(response.tool_calls, (tuple, list))
                or any(not isinstance(call, ToolCall) for call in response.tool_calls)):
            return finish('failed', 'protocol_error')
        if response.requires_user_input and not response.text.strip():
            return finish('failed', 'protocol_error')
        calls = deepcopy(tuple(response.tool_calls))
        if not calls:
            if not response.text.strip():
                return finish('failed', 'protocol_error')
            state.messages.append(AssistantMessage(response.text))
            if response.requires_user_input:
                return finish('waiting_user', 'user_input_required', response.text)
            return finish('answered', 'final_answer', response.text)
        # Text accompanying proposals is not a final answer.
        state.messages.append(AssistantMessage(response.text, calls))
        state.status = 'requires_tools'
        if len(calls) > state.max_tool_calls - state.tool_call_count:
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

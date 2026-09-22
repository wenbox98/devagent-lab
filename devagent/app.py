"""L00: validate input, call once, then validate the response."""
from pathlib import Path
from uuid import uuid4

from .models import ModelRequest, RunResult
from .tools.protocol import ToolSpec
from .config import ConfigMissingError
from .providers.adapter import (ProviderAuthenticationError, ProviderRateLimitError,
                                ProviderResponseError, ProviderServiceError,
                                ProviderTimeoutError)
from .trace import DEFAULT_TRACE_PATH, TraceWriter


def run_task(task: str, client, *, trace_path: str | Path = DEFAULT_TRACE_PATH,
             max_chars: int = 5000, tools: tuple[ToolSpec, ...] = ()) -> RunResult:
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError('max_chars must be a positive integer')
    run_id = str(uuid4())
    trace = TraceWriter(trace_path, run_id)

    def emit(event, **fields):
        # Catch I/O only at the trace boundary, not client-side OSError.
        try:
            trace.emit(event, **fields)
        except OSError:
            return False
        return True

    def trace_failure():
        return RunResult(run_id, 'failed', None, 'trace_io', 5)

    def finish(output=None, error_code=None, exit_code=0, response=None, status=None):
        status = status or ('succeeded' if error_code is None else 'failed')
        if not emit('run_finished', status=status, error_code=error_code, exit_code=exit_code):
            return trace_failure()
        metadata = {} if response is None else {
            'provider': response.provider, 'model': response.model,
            'input_tokens': response.input_tokens, 'output_tokens': response.output_tokens,
            'tool_calls': response.tool_calls,
        }
        return RunResult(run_id, status, output, error_code, exit_code, **metadata)

    if not emit('run_started', status='started'):
        return trace_failure()
    if not isinstance(task, str) or not task.strip():
        return finish(error_code='invalid_input', exit_code=2)
    request = ModelRequest(task=task.strip(), tools=tools)
    if len(request.task) > max_chars:
        return finish(error_code='input_too_long', exit_code=2)
    if not emit('model_started', status='started', task_chars=len(request.task)):
        return trace_failure()
    try:
        response = client.complete(request)
    except ConfigMissingError:
        if not emit('model_finished', status='failed', error_code='config_missing'):
            return trace_failure()
        return finish(error_code='config_missing', exit_code=6)
    except ProviderAuthenticationError:
        if not emit('model_finished', status='failed', error_code='provider_authentication'):
            return trace_failure()
        return finish(error_code='provider_authentication', exit_code=7)
    except ProviderRateLimitError:
        if not emit('model_finished', status='failed', error_code='provider_rate_limit'):
            return trace_failure()
        return finish(error_code='provider_rate_limit', exit_code=8)
    except ProviderTimeoutError:
        if not emit('model_finished', status='failed', error_code='provider_timeout'):
            return trace_failure()
        return finish(error_code='provider_timeout', exit_code=3)
    except ProviderResponseError:
        if not emit('model_finished', status='failed', error_code='provider_parse_error'):
            return trace_failure()
        return finish(error_code='provider_parse_error', exit_code=4)
    except ProviderServiceError:
        if not emit('model_finished', status='failed', error_code='provider_service_error'):
            return trace_failure()
        return finish(error_code='provider_service_error', exit_code=9)
    except TimeoutError:
        if not emit('model_finished', status='failed', error_code='model_timeout'):
            return trace_failure()
        return finish(error_code='model_timeout', exit_code=3)
    if not emit('model_finished', status='succeeded', provider=response.provider,
                model=response.model, input_tokens=response.input_tokens,
                output_tokens=response.output_tokens):
        return trace_failure()
    # ModelResponse is the current client contract; other types are a learner exercise.
    if response.tool_calls:
        # A proposal is pending work, not proof of execution or task completion.
        return finish(output=response.text or None, response=response, status='requires_tools')
    if not response.text.strip():
        return finish(error_code='invalid_response', exit_code=4)
    return finish(output=response.text, response=response)

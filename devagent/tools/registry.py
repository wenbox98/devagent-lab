"""Fixed read-only registry. The host binds workspace; arguments cannot override it."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from . import files
from .protocol import ToolCall, ToolError, ToolResult, ToolSpec


def validate_arguments(spec: ToolSpec, arguments) -> dict:
    """Validate the small schema subset used by our two tools, not full JSON Schema.

    This checks structure/ranges only; filesystem authorization remains in L02.
    """
    if not isinstance(arguments, dict):
        raise ValueError('arguments must be an object')
    schema = spec.input_schema
    properties = schema['properties']
    if set(arguments) - set(properties):
        raise ValueError('unknown arguments are not allowed')
    if set(schema['required']) - set(arguments):
        raise ValueError('missing required arguments')
    for name, value in arguments.items():
        rule = properties[name]
        expected = rule['type']
        if expected == 'string' and not isinstance(value, str):
            raise ValueError(f'{name} must be a string')
        if expected == 'integer' and (type(value) is not int or value < rule['minimum']):
            raise ValueError(f'{name} must be a positive integer')
    if 'end_line' in arguments and arguments['end_line'] < arguments.get('start_line', 1):
        raise ValueError('end_line must not precede start_line')
    return dict(arguments)


class ToolRegistry:
    """One synchronous dispatch or batch. No retries, model loop or durable deduplication."""

    def __init__(self, workspace: str | Path):
        self._workspace = Path(workspace).resolve()
        self._entries = {
            'read_file': (ToolSpec(
                'read_file',
                'Read allowed UTF-8 text in the host-controlled workspace; path cannot expand it. '
                'start_line is 1-based and end_line is inclusive (omit it for EOF). '
                'Whole-file max_bytes and returned max_lines are fixed by the host/L02 defaults. '
                'The result may contain next_start_line when file lines remain. '
                'Not for arbitrary OS paths, binary or oversized files.',
                {'type': 'object', 'properties': {
                    'path': {'type': 'string'},
                    'start_line': {'type': 'integer', 'minimum': 1},
                    'end_line': {'type': 'integer', 'minimum': 1}},
                 'required': ['path'], 'additionalProperties': False}), self._read),
            'list_files': (ToolSpec(
                'list_files',
                'List exposable files and their whole-file byte sizes in the host-controlled '
                'workspace, using L02 filtering. This does not grant access to arbitrary OS paths.',
                {'type': 'object', 'properties': {}, 'required': [],
                 'additionalProperties': False}), self._list),
        }
        self.handler_calls = 0

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        # A caller editing advertised schemas must not change runtime authorization.
        return tuple(deepcopy(entry[0]) for entry in self._entries.values())

    def _read(self, arguments: dict):
        return asdict(files.read_file(self._workspace, **arguments))

    def _list(self, arguments: dict):
        return files.list_files(self._workspace)

    @staticmethod
    def _failure(call: ToolCall, code: str, message: str) -> ToolResult:
        return ToolResult(call.call_id, False, error=ToolError(code, message))

    def execute(self, call: ToolCall) -> ToolResult:
        if not isinstance(call.call_id, str) or not call.call_id.strip():
            return self._failure(call, 'protocol_error', 'call_id must be nonempty text')
        if not isinstance(call.name, str) or call.name not in self._entries:
            return self._failure(call, 'unknown_tool', 'tool is not registered')
        spec, handler = self._entries[call.name]
        try:
            arguments = validate_arguments(spec, call.arguments)
        except ValueError as exc:
            return self._failure(call, 'invalid_args', str(exc))
        self.handler_calls += 1
        try:
            data = handler(arguments)
        except files.FileAccessError as exc:
            return self._failure(call, exc.code, str(exc))
        # Unexpected programming errors propagate rather than becoming fake business failures.
        return ToolResult(call.call_id, True, data=data)

    def execute_batch(self, calls: list[ToolCall] | tuple[ToolCall, ...]) -> list[ToolResult]:
        """Invalid/duplicate IDs reject the entire batch before any handler runs.

        Rejected results follow input positions and preserve IDs; a duplicate-ID
        batch must not be interpreted as a successful ID-to-result mapping.
        """
        calls = tuple(calls)
        if any(not isinstance(call.call_id, str) or not call.call_id.strip() for call in calls):
            return [self._failure(call, 'protocol_error', 'batch has an invalid call_id') for call in calls]
        if any(count > 1 for count in Counter(call.call_id for call in calls).values()):
            return [self._failure(call, 'protocol_error', 'batch has duplicate call_id') for call in calls]
        return [self.execute(call) for call in calls]

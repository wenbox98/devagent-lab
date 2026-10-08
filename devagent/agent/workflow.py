"""Fixed read-only list -> read -> versioned evidence workflow, using L03 tools."""
from dataclasses import dataclass

from .citations import Citation, CitationError, citation_from_read
from ..tools.files import FileReadResult
from ..tools.protocol import ToolCall, ToolResult
from ..tools.registry import ToolRegistry


@dataclass(frozen=True)
class ReadPlan:
    path: str
    start_line: int = 1
    end_line: int = 6

    def __post_init__(self):
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError('path must be nonempty text')
        if type(self.start_line) is not int or type(self.end_line) is not int or not 1 <= self.start_line <= self.end_line:
            raise ValueError('line range must be 1-based and ordered')

    @property
    def task(self):
        return f'List allowed files, then read {self.path} lines {self.start_line}..{self.end_line}; return the actual text and citation.'

    @property
    def arguments(self):
        return {'path': self.path, 'start_line': self.start_line, 'end_line': self.end_line}


@dataclass(frozen=True)
class WorkflowResult:
    status: str
    output: str | None
    evidence: tuple[Citation, ...]
    results: tuple[ToolResult, ...]
    tool_calls: int
    model_calls: int = 0
    error_code: str | None = None


def run_readonly_workflow(plan: ReadPlan, registry: ToolRegistry) -> WorkflowResult:
    results = []
    for call in (ToolCall('list', 'list_files', {}), ToolCall('read', 'read_file', plan.arguments)):
        result = registry.execute(call)
        results.append(result)
        if not result.ok:
            return WorkflowResult('failed', None, (), tuple(results), len(results), error_code=result.error.code)
    read = FileReadResult(**results[-1].data)
    try:
        citation = citation_from_read(read)
        registry.validate_citation(citation)
    except CitationError as exc:
        return WorkflowResult('failed', None, (), tuple(results), len(results), error_code=exc.code)
    return WorkflowResult('answered', read.content, (citation,), tuple(results), len(results))

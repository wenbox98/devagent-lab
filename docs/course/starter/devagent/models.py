from dataclasses import dataclass

@dataclass(frozen=True)
class ModelRequest:
    task: str

@dataclass(frozen=True)
class ModelResponse:
    text: str
    provider: str

@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    output: str | None
    error_code: str | None
    exit_code: int

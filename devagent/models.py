from dataclasses import dataclass

@dataclass(frozen=True)
class ModelRequest:
    task: str

@dataclass(frozen=True)
class ModelResponse:
    text: str
    provider: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    output: str | None
    error_code: str | None
    exit_code: int
    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

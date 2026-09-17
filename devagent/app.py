"""L00练习起点。按02实现，不从网上安装名为devagent的包。"""
from uuid import uuid4

from .models import RunResult

def run_task(task: str, client) -> RunResult:
    if not isinstance(task, str) or not task.strip():
        return RunResult(
            run_id=str(uuid4()),
            status="failed",
            output=None,
            error_code="invalid_input",
            exit_code=2,
        )
    raise NotImplementedError('L00尚未实现；请按docs/course/lessons/L00/02-交给AI.md增量完成')

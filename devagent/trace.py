"""Append-only diagnostic metadata; no task or response bodies."""
import json
from pathlib import Path
from time import perf_counter

DEFAULT_TRACE_PATH = Path('.local/traces/runs.jsonl')


class TraceWriter:
    def __init__(self, path, run_id):
        self.path = Path(path)
        self.run_id = run_id
        self.started = perf_counter()
        self.sequence = 0

    def emit(self, event, **fields):
        self.sequence += 1
        record = dict(run_id=self.run_id, sequence=self.sequence, event=event,
                      elapsed_ms=(perf_counter() - self.started) * 1000, **fields)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')

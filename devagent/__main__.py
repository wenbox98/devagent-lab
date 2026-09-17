"""Application CLI: exit codes express the business result."""
import argparse
from dataclasses import asdict
import json
from .app import run_task
from .fake_model import FakeModelClient
from .trace import DEFAULT_TRACE_PATH


def main():
    parser = argparse.ArgumentParser(description='L00 simulated model request')
    parser.add_argument('--task', required=True)
    parser.add_argument('--mode', choices=['success', 'timeout', 'bad_response'], default='success')
    parser.add_argument('--trace-path', default=str(DEFAULT_TRACE_PATH))
    args = parser.parse_args()
    result = run_task(args.task, FakeModelClient(args.mode), trace_path=args.trace_path)
    print(json.dumps(asdict(result), ensure_ascii=False))
    return result.exit_code


if __name__ == '__main__':
    raise SystemExit(main())

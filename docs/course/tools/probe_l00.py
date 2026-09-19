"""Observe handle(task, client) in the learner's L00 concept copy.
This executes the learner's trusted local example, not a sandbox for untrusted code.
The probe records errors instead of silently converting them to expected domain errors.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
import io
import hashlib
import json
from pathlib import Path
import runpy
import sys

def probe(project: Path, task, response='ok') -> dict:
    project = project.resolve()
    rel = Path('.local/concepts/L00/00-example.py')
    current = project
    for part in rel.parts:
        current /= part
        if current.is_symlink(): raise ValueError('拒绝跟随概念副本中的符号链接。')
    target = project / rel
    if not target.is_file():
        raise ValueError('先运行prepare_example.py L00 --project .创建练习副本。')
    captured = io.StringIO()
    with redirect_stdout(captured):
        namespace = runpy.run_path(str(target), run_name='concept_probe')
    function = namespace.get('handle')
    if not callable(function): raise ValueError('概念副本没有可调用的handle；本探针不猜其他函数。')
    calls=[];result=None;exception=None;message=None
    def client(clean_task):
        calls.append(clean_task);return response
    try:
        with redirect_stdout(captured): result=function(task,client)
    except Exception as exc:
        exception=type(exc).__name__;message=str(exc)
    return {'object':'L00_concept_copy_not_generated_application',
            'file':rel.as_posix(),'source_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'function':'handle','task':task,'task_type':type(task).__name__,
            'result':result,'exception_type':exception,'exception_message':message,
            'client_calls':len(calls),'client_arguments':calls,
            'example_stdout':captured.getvalue(),
            'note':'观察记录，不代表已达到目标合同；异常不会被探针转换成invalid_input。'}

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path('.'))
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--task-json',help='JSON input, e.g. 42 or null')
    group.add_argument('--task-text',help='Use a string directly without JSON quote escaping')
    p.add_argument('--response-json',default='"ok"')
    a=p.parse_args()
    try: result=probe(a.project,json.loads(a.task_json) if a.task_json is not None else a.task_text,json.loads(a.response_json))
    except Exception as exc:
        print(json.dumps({'status':'blocked','error':str(exc)},ensure_ascii=False));return 2
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0

if __name__=='__main__': raise SystemExit(main())

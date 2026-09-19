"""DevAgent v4.2学习助手。标准库；不联网、不调用模型、不自动提交Git。"""
from __future__ import annotations
import argparse
from datetime import date, timedelta
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=json.loads((ROOT/'course-manifest.json').read_text(encoding='utf-8'))

def emit(x): print(json.dumps(x,ensure_ascii=False,indent=2))

def init_project(args):
    dest=args.destination.resolve()
    if dest.exists(): raise ValueError('目标已存在；为避免覆盖，init只接受全新目录。已有项目按迁移指南手动更新docs/course。')
    if dest.is_relative_to(ROOT): raise ValueError('项目不能放在教材目录内部，否则会递归复制。')
    shutil.copytree(ROOT/'starter',dest)
    shutil.copytree(ROOT,dest/'docs/course',ignore=shutil.ignore_patterns('__pycache__','*.pyc','.local'))
    shutil.copytree(ROOT/'fixtures',dest/'fixtures')
    (dest/'docs/learning-records').mkdir(parents=True)
    shutil.copy2(ROOT/'templates/progress.json',dest/'docs/learning-records/progress.json')
    emit({'created':str(dest),'state':'L00 scaffold, not implemented','next':['cd '+str(dest),'git init','python -m unittest discover -s tests -v'],'expected':'首次L00测试因NotImplementedError报错；按L00/02实现后才转绿。'})

def doctor(args):
    packages={}
    for p in ['langchain','langchain-core','langgraph','langgraph-checkpoint-sqlite','pydantic','numpy']:
        try: packages[p]=importlib.metadata.version(p)
        except importlib.metadata.PackageNotFoundError:packages[p]='missing'
    result={'python':platform.python_version(),'python_baseline_ok':sys.version_info>=(3,12),'platform':platform.platform(),'git':shutil.which('git'),'packages':packages,'paid_api_called':False,'note':'框架缺失不阻塞L00。F课需要单独依赖检查；此命令不证明版本兼容或框架行为正确。'}
    emit(result)
    return 0 if result['python_baseline_ok'] else 2

def pack(args):
    lesson=args.lesson.upper()
    if lesson not in MANIFEST['lessons']:raise ValueError('未知课号')
    project=args.project.resolve(); output=args.output.resolve()
    if not (project/'devagent').is_dir():raise ValueError('未找到devagent目录；请指定真实学习项目根目录。')
    if output.exists():raise ValueError('输出已存在，拒绝覆盖。请使用新文件名。')
    dirs=['devagent','tests','fixtures','evaluation','java-task-service/src']
    names=['README.md','pyproject.toml','requirements.txt','requirements-framework.txt','requirements-framework.in','uv.lock','poetry.lock','pom.xml','java-task-service/pom.xml']
    names += [f'docs/learning-records/{lesson}-code-map.json', f'docs/learning-records/{lesson}-handoff.json']
    candidates=[]
    for name in dirs:
        d=project/name
        if d.exists():candidates.extend(p for p in d.rglob('*') if p.is_file())
    candidates.extend(project/name for name in names if (project/name).is_file())
    secret=re.compile(rb'(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|sk-[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16})')
    allowed={'.py','.java','.sql','.json','.jsonl','.toml','.yaml','.yml','.xml','.txt','.md','.properties','.lock'}
    selected=[];total=0
    for p in sorted(set(candidates)):
        if p.is_symlink():continue
        rel=p.relative_to(project)
        if any(x in {'.git','.venv','__pycache__','.local','target','node_modules'} for x in rel.parts):continue
        if p.name.startswith('.env') or p.suffix.lower() not in allowed:continue
        if any(x in p.name.lower() for x in ['credential','secret','private-key']):continue
        if not p.resolve().is_relative_to(project):continue
        data=p.read_bytes()
        if len(data)>1_000_000:raise ValueError(f'文件过大，请检查后精简：{rel}')
        if secret.search(data):raise ValueError(f'检测到疑似密钥，停止打包：{rel}')
        total+=len(data)
        if total>15_000_000:raise ValueError('源码包超过15MB，请移除数据与生成文件后重试。')
        selected.append((rel.as_posix(),data))
    try:
        r=subprocess.run(['git','rev-parse','HEAD'],cwd=project,text=True,capture_output=True,timeout=5)
        head=r.stdout.strip() if r.returncode==0 else None
    except (FileNotFoundError,subprocess.TimeoutExpired):head=None
    index={'lesson':lesson,'course_version':MANIFEST['version'],'source_head':head,'files':[{'path':n,'sha256':hashlib.sha256(b).hexdigest()} for n,b in selected],'warning':'只检测少量密钥模式，不保证没有敏感信息。上传前人工检查；不含答案、整个教材、日志和环境文件。'}
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as z:
        z.writestr(f'{lesson}-02-交给AI.md',(ROOT/'lessons'/lesson/'02-交给AI.md').read_bytes())
        z.writestr('source-manifest.json',json.dumps(index,ensure_ascii=False,indent=2))
        for n,b in selected:z.writestr(n,b)
    emit({'output':str(output),'source_files':len(selected),'required_md':f'{lesson}-02-交给AI.md','warning':index['warning']})

def lab(args):
    project=args.project.resolve();dest=project/'.local/workshops/bug_lab'
    if dest.exists():raise ValueError('练习副本已经存在，拒绝覆盖你的修改。')
    shutil.copytree(ROOT/'workshops/bug_lab',dest)
    emit({'created':str(dest),'run':'python -m unittest discover -s .local/workshops/bug_lab -v','expected':'初始包含8类故意错误；只修改student.py，不改测试。参考答案不在此副本中。'})

def review(args):
    content=json.loads(args.progress.read_text(encoding='utf-8'))
    today=date.fromisoformat(args.today) if args.today else date.today()
    due=[]
    for lesson,raw in content.get('completed',{}).items():
        if lesson not in MANIFEST['lessons']:raise ValueError('未知课号：'+lesson)
        start=date.fromisoformat(raw)
        for offset in [1,3,7,21]:
            target=start+timedelta(days=offset)
            due.append({'lesson':lesson,'check':f'D{offset}','date':target.isoformat(),'due':target<=today})
    emit({'today':today.isoformat(),'review_dates':due,'note':'仅计算复习日，不自动设提醒、不记录掌握、不判断已复测。完成复测在个人记录填写。'})

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('init');p.add_argument('destination',type=Path);p.set_defaults(func=init_project)
    p=sub.add_parser('doctor');p.set_defaults(func=doctor)
    p=sub.add_parser('pack');p.add_argument('lesson');p.add_argument('--project',type=Path,default=Path('.'));p.add_argument('--output',type=Path,required=True);p.set_defaults(func=pack)
    p=sub.add_parser('lab');p.add_argument('--project',type=Path,default=Path('.'));p.set_defaults(func=lab)
    p=sub.add_parser('review');p.add_argument('progress',type=Path);p.add_argument('--today');p.set_defaults(func=review)
    args=parser.parse_args()
    try:return args.func(args) or 0
    except (ValueError,OSError,json.JSONDecodeError) as exc:
        emit({'status':'blocked','error':str(exc)});return 2

if __name__=='__main__':raise SystemExit(main())

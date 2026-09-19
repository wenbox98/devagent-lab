"""公共独立验收器：忽略Agent自述，实测受控分页工作区。不是恶意代码沙箱。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    args=parser.parse_args();ws=args.workspace.resolve();base=ROOT/'fixtures/tiny_repo'
    if not (ws/'pagination.py').is_file():
        print(json.dumps({'status':'blocked','reason':'pagination.py missing'}));return 2
    expected={p.relative_to(base).as_posix():p for p in base.rglob('*') if p.is_file()}
    actual={p.relative_to(ws).as_posix():p for p in ws.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    scope_ok=(set(actual)==set(expected) and all(digest(actual[n])==digest(p) for n,p in expected.items() if n!='pagination.py'))
    if any(p.is_symlink() for p in ws.rglob('*')):
        print(json.dumps({'status':'failed','reason':'symlink_not_allowed'}));return 1
    if not scope_ok:
        print(json.dumps({'status':'failed','scope_ok':False,'reason':'unauthorized_file_change'}));return 1
    before=digest(ws/'pagination.py')
    try:
        run=subprocess.run([sys.executable,'-I','-B',str(ROOT/'tools/_fixture_tests.py'),str(ws)],text=True,capture_output=True,timeout=8)
        try: tests=json.loads(run.stdout.strip())
        except (ValueError,TypeError):tests={}
    except subprocess.TimeoutExpired:
        print(json.dumps({'status':'failed','reason':'timeout','scope_ok':scope_ok}));return 1
    after=digest(ws/'pagination.py') if (ws/'pagination.py').exists() else None
    after_files={p.relative_to(ws).as_posix():p for p in ws.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    scope_ok=(set(after_files)==set(expected) and not any(p.is_symlink() for p in ws.rglob('*')) and all(digest(after_files[n])==digest(p) for n,p in expected.items() if n!='pagination.py'))
    ok=(scope_ok and before==after and run.returncode==0 and tests.get('collected',0)>0 and tests.get('failures')==0 and tests.get('errors')==0 and tests.get('skipped')==0)
    result={'status':'passed' if ok else 'failed','scope_ok':scope_ok,'snapshot_unchanged':before==after,'snapshot_hash':before,'test_program_sha256':digest(ROOT/'tools/_fixture_tests.py'),'exit_code':run.returncode,'tests':tests,'stderr':run.stderr[-6000:],'scope':'public controlled fixture; not sandbox or hidden graduation exam'}
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if ok else 1

if __name__=='__main__': raise SystemExit(main())

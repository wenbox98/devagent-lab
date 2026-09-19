"""Copy the supplied lesson example to a personal, non-overwriting exercise directory.
Run from the learning project: python docs/course/tools/prepare_example.py L00 --project .
No application execution, network access, API use or Git changes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]

def prepare(lesson: str, project: Path) -> dict:
    manifest = json.loads((ROOT / 'course-manifest.json').read_text(encoding='utf-8'))
    lesson = lesson.upper()
    if lesson not in manifest['lessons']:
        raise ValueError('未知课号；请使用course-manifest.json中的固定ID。')
    project = project.resolve()
    if not project.is_dir() or not (project / 'devagent').is_dir():
        raise ValueError('请选择含devagent/的学习项目根目录；教材目录不是应用目录。')
    if project == ROOT or project.is_relative_to(ROOT):
        raise ValueError('不能把教材目录当作学习项目。')
    relative = Path('.local') / 'concepts' / lesson
    dest = project / relative
    current = project
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('练习目标或父目录是符号链接，拒绝跟随。')
    if dest.exists():
        raise ValueError('本课副本已存在；为保留你的改动，不覆盖。直接使用现有副本。')
    source = ROOT / manifest['lessons'][lesson]['example_file']
    if not source.is_file() or source.is_symlink():
        raise ValueError('教材基准文件缺失或不是普通文件。')
    dest.mkdir(parents=True, exist_ok=False)
    try:
        target = dest / source.name
        shutil.copy2(source, target)
        info = {'lesson': lesson, 'course_version': manifest['version'],
                'source': source.relative_to(ROOT).as_posix(),
                'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'copy': (relative / source.name).as_posix(),
                'note': '只复制概念示例；没有生成应用或安装框架。不要编辑基准或公共答案。'}
        (dest / 'source.json').write_text(json.dumps(info, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        return {'status': 'prepared', **info}
    except Exception:
        # The directory was exclusively created by this call; no pre-existing work is removed.
        shutil.rmtree(dest)
        raise

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('lesson')
    parser.add_argument('--project', type=Path, default=Path('.'))
    args = parser.parse_args()
    try:
        result = prepare(args.lesson, args.project)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'status': 'blocked', 'error': str(exc)}, ensure_ascii=False)); return 2
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0

if __name__ == '__main__':
    raise SystemExit(main())

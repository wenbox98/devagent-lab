"""机制实验：受控临时目录的路径授权与字节上限；不是完整文件工具/沙箱。
不实现独立练习max_lines，不访问用户业务文件，不改主项目。
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import json

class Denied(Exception):
    pass
class TooLarge(Exception):
    pass

def authorized_target(root, supplied):
    root = Path(root).resolve(strict=True)
    target = (root / supplied).resolve()
    if not target.is_relative_to(root):
        raise Denied("outside workspace")
    return target

def bounded_bytes(target, budget):
    # 本实验只操作自己创建的普通文件；完整工具还需类型/后缀/权限策略。
    with target.open("rb") as stream:
        data = stream.read(budget + 1)
    if len(data) > budget:
        raise TooLarge("byte budget exceeded")
    return data

def main():
    with TemporaryDirectory(prefix="devagent-mechanism-") as directory:
        base = Path(directory)
        root = base / "repo"
        root.mkdir()
        (root / "a.txt").write_bytes(b"abcd")
        target = authorized_target(root, "a.txt")
        assert bounded_bytes(target, 4) == b"abcd"
        denied = False
        try:
            authorized_target(root, "../outside.txt")
        except Denied:
            denied = True
        assert denied
        over = False
        try:
            bounded_bytes(target, 3)
        except TooLarge:
            over = True
        assert over
        print(json.dumps({"scope":"controlled-temp-files", "exact_limit":"accepted",
                          "outside":"denied-before-open", "over_limit":"rejected", "verified":True}))

if __name__ == "__main__":
    main()

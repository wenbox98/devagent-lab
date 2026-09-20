"""机制实验：版本条件写+唯一片段匹配。受控临时普通文件、单写者假设。
不是并发安全平台，不包含多文件事务，不替代项目授权工具。
"""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import os, json

def digest(data):
    return sha256(data).hexdigest()

def apply(path, base_hash, old, new):
    before = path.read_bytes()  # 只用于本实验自己创建的小文件。
    if digest(before) != base_hash:
        return "stale_version"
    if before.count(old) != 1:
        return "ambiguous_match"
    after = before.replace(old, new, 1)
    temporary = path.with_name(path.name + ".pending")
    temporary.write_bytes(after)
    os.replace(temporary, path)
    return "applied"

def main():
    with TemporaryDirectory(prefix="devagent-patch-") as directory:
        path = Path(directory) / "page.py"
        path.write_bytes(b"start = page_no * size\n")
        old_hash = digest(path.read_bytes())
        path.write_bytes(b"# other change\nstart = page_no * size\n")
        changed = path.read_bytes()
        assert apply(path, old_hash, b"page_no", b"(page_no - 1)") == "stale_version"
        assert path.read_bytes() == changed
        assert apply(path, digest(changed), b"page_no", b"(page_no - 1)") == "applied"
        assert b"(page_no - 1)" in path.read_bytes()
        print(json.dumps({"scope":"single-writer-temp-file", "stale":"rejected_without_write",
                          "fresh":"applied", "verified":True}))

if __name__ == "__main__":
    main()

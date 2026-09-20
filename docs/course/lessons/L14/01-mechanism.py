"""机制实验：分页续读绑定查询和版本；数据仅为内存样本。"""
from dataclasses import dataclass
import json

@dataclass(frozen=True)
class Cursor:
    query: str
    version: str
    offset: int

def page(items, query, version, limit, cursor=None):
    if type(limit) is not int or limit < 1:
        raise ValueError("invalid limit")
    if cursor is not None and (cursor.query != query or cursor.version != version):
        raise ValueError("stale_or_wrong_cursor")
    start = 0 if cursor is None else cursor.offset
    selected = items[start:start + limit]
    end = start + len(selected)
    next_cursor = Cursor(query, version, end) if end < len(items) else None
    return selected, next_cursor

def main():
    first, cursor = page(["A", "B", "C"], "page", "v1", 2)
    assert first == ["A", "B"] and cursor.offset == 2
    last, end = page(["A", "B", "C"], "page", "v1", 2, cursor)
    assert last == ["C"] and end is None
    rejected = False
    try:
        page(["X", "A", "B", "C"], "page", "v2", 2, cursor)
    except ValueError:
        rejected = True
    assert rejected
    print(json.dumps({"scope":"in-memory-versioned-pagination", "pages":[first,last],
                      "stale_cursor_rejected":True, "verified":True}))

if __name__ == "__main__":
    main()

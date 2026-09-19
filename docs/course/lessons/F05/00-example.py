"""SQLite内部原子记录的幂等演示，不宣称保护了任意外部副作用。"""
import hashlib
import sqlite3
import tempfile
from pathlib import Path

def submit(db: Path, operation_id: str, body: str) -> str:
    fingerprint = hashlib.sha256(body.encode()).hexdigest()
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS effects (op TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)")
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT fingerprint FROM effects WHERE op=?", (operation_id,)).fetchone()
        if row:
            if row[0] != fingerprint:
                raise ValueError("idempotency_conflict")
            return "reused"
        conn.execute("INSERT INTO effects VALUES (?,?)", (operation_id, fingerprint))
        return "created"

def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        db = Path(temp) / "effects.sqlite"
        print(submit(db, "op-1", "body-A"))
        # 新连接模拟重新读取持久状态；这不是完整的子进程恢复测试。
        print(submit(db, "op-1", "body-A"))
        try:
            submit(db, "op-1", "body-B")
        except ValueError as exc:
            print(str(exc))
        else:
            raise AssertionError("different request reused a key")
        with sqlite3.connect(db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
        assert count == 1
        print("effect_count:", count)

if __name__ == "__main__":
    main()

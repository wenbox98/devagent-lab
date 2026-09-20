"""机制实验：两个独立进程使用同一SQLite持久状态。
不是LangGraph检查点验证，也不证明外部副作用恰好一次。
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import json, sqlite3, subprocess, sys

def child(mode, db):
    with sqlite3.connect(db) as connection:
        if mode == "write":
            connection.execute("CREATE TABLE checkpoint (id TEXT PRIMARY KEY, state TEXT NOT NULL)")
            connection.execute("INSERT INTO checkpoint VALUES (?, ?)", ("task1", "waiting"))
        else:
            row = connection.execute("SELECT state FROM checkpoint WHERE id=?", ("task1",)).fetchone()
            assert row == ("waiting",)
            print(row[0])

def main():
    with TemporaryDirectory(prefix="devagent-persist-") as directory:
        db = str(Path(directory) / "checkpoint.sqlite")
        script = str(Path(__file__).resolve())
        subprocess.run([sys.executable, script, "write", db], check=True, timeout=10)
        result = subprocess.run([sys.executable, script, "read", db], capture_output=True,
                                text=True, encoding="utf-8", check=True, timeout=10)
        assert result.stdout.strip() == "waiting"
        print(json.dumps({"scope":"sqlite-cross-process-not-langgraph", "recovered":"waiting",
                          "process_count":2, "verified":True}))

if __name__ == "__main__":
    if len(sys.argv) == 3:
        child(sys.argv[1], sys.argv[2])
    else:
        main()

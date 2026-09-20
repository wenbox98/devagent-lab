"""机制实验：SQLite条件更新领取。并发worker争同一记录，仅一方成功。
没有网络服务/消息队列；不证明崩溃恢复和副作用幂等。
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import json, sqlite3

def claim(db):
    with sqlite3.connect(db, timeout=10) as connection:
        cursor = connection.execute(
            "UPDATE tasks SET state='running', version=version+1 "
            "WHERE id=? AND state='queued' AND version=0", ("t1",))
        return cursor.rowcount

def main():
    with TemporaryDirectory(prefix="devagent-claim-") as directory:
        db = str(Path(directory) / "tasks.sqlite")
        with sqlite3.connect(db) as connection:
            connection.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, state TEXT, version INTEGER)")
            connection.execute("INSERT INTO tasks VALUES ('t1','queued',0)")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(claim, [db] * 12))
        assert sum(results) == 1
        with sqlite3.connect(db) as connection:
            final = connection.execute("SELECT state,version FROM tasks WHERE id='t1'").fetchone()
        assert final == ("running", 1)
        print(json.dumps({"scope":"sqlite-conditional-claim", "attempts":len(results),
                          "successful_claims":sum(results), "state":final[0], "verified":True}))

if __name__ == "__main__":
    main()

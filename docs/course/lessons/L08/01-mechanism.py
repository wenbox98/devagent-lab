"""机制实验：超时停止等待后还要终止并wait直接子进程。
仅执行本脚本固定的sleep，不运行外部仓库/用户命令。
不证明进程树/容器/Windows Job Object隔离。
"""
import json, subprocess, sys

def main():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    timed_out = False
    try:
        process.wait(timeout=0.05)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    assert timed_out
    assert process.poll() is not None
    print(json.dumps({"scope":"controlled-direct-child-only", "timed_out":timed_out,
                      "exit_confirmed":True, "verified":True}))

if __name__ == "__main__":
    main()

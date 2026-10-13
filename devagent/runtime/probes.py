"""Trusted literal probes; no repository imports, user source or arbitrary argv.

These exercise lifecycle mechanisms on the host. They MUST NOT be presented as
proof of sandbox isolation or used as a fallback for repository tests.
"""

CHILD = """import os, time
with open('heartbeat.txt', 'ab', buffering=0) as stream:
    while True:
        stream.write(b'.')
        time.sleep(0.02)
"""

PROBES = {
    'normal': """import json, os, unittest
class SmallTest(unittest.TestCase):
    def test_sum(self):
        self.assertEqual(sum([1, 2]), 3)
suite = unittest.defaultTestLoader.loadTestsFromTestCase(SmallTest)
result = unittest.TextTestRunner().run(suite)
print(json.dumps({'tests_run': result.testsRun, 'passed': result.wasSuccessful(),
                  'env_keys': sorted(os.environ)}), flush=True)
raise SystemExit(0 if result.wasSuccessful() else 1)
""",
    'nonzero': "import sys; print('PASS is only text'); sys.exit(7)",
    'timeout': f"""import json, os, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-I', '-S', '-u', '-c', {CHILD!r}])
print(json.dumps({{'parent_pid': os.getpid(), 'child_pid': child.pid}}), flush=True)
time.sleep(30)
""",
    'orphan': f"""import json, subprocess, sys
child = subprocess.Popen([sys.executable, '-I', '-S', '-u', '-c', {CHILD!r}])
print(json.dumps({{'child_pid': child.pid}}), flush=True)
""",
    'output-limit': """import os
while True:
    os.write(1, b'O' * 1024)
    os.write(2, b'E' * 1024)
""",
    'dual-stream': """import os, threading
def write(fd, value):
    for _ in range(64):
        os.write(fd, value * 1024)
threads = [threading.Thread(target=write, args=(1, b'O')),
           threading.Thread(target=write, args=(2, b'E'))]
for thread in threads: thread.start()
for thread in threads: thread.join()
""",
    'unicode': "import os; os.write(1, ('中文' * 1000).encode('utf-8'))",
}


def probe_argv(python: str, name: str) -> tuple[str, ...]:
    if not isinstance(name, str) or name not in PROBES:
        raise ValueError('unknown trusted probe')
    # The fixed bootstrap cannot spawn or execute the probe until Job assignment.
    bootstrap = "import sys\nif sys.stdin.buffer.readline() != b'GO\\n': raise SystemExit(125)\n"
    return python, '-I', '-S', '-u', '-c', bootstrap + PROBES[name]

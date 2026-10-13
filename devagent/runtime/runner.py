"""L08 prepare/start/observe/finish with explicit execution scope.

Repository execution is blocked without a verified sandbox. run_probe is a
separate trusted-host diagnostic: only audited literal programs from probes.py,
never caller source, repository imports, shell commands or a fallback mode.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Lock, Thread
from time import monotonic, sleep

from .environment import child_environment, inspect_environment
from .probes import probe_argv
from .windows_job import WindowsJob
from ..tools import files
from ..tools.protocol import ToolError

TEST_ARGUMENTS = ('-I', '-m', 'unittest', 'discover', '-s', 'tests', '-v')


@dataclass(frozen=True)
class RunnerLimits:
    timeout_ms: int = 1000
    max_output_bytes: int = 4096
    cleanup_ms: int = 1500

    def __post_init__(self):
        for name, ceiling in (('timeout_ms', 30000), ('max_output_bytes', 1024 * 1024), ('cleanup_ms', 5000)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError(f'{name} must be a positive integer within the host ceiling')


@dataclass(frozen=True)
class RunCommandResult:
    exit_code: int | None
    timed_out: bool
    truncated: bool
    stdout: str
    stderr: str
    duration_ms: int
    status: str
    started: bool = False
    termination_confirmed: bool | None = None
    cleanup_confirmed: bool | None = None
    captured_bytes: int = 0
    active_processes_after: int | None = None
    scope: str = 'repository'
    error: ToolError | None = None


@dataclass(frozen=True)
class _Prepared:
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    scope: str


class _Blocked(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class _StartFailure(OSError):
    def __init__(self, started, confirmed):
        self.started, self.confirmed = started, confirmed
        super().__init__('process/Job setup failed before releasing the trusted gate')


class _OutputCapture:
    """Two readers, one shared raw-byte budget; no unbounded output queue."""
    def __init__(self, limit):
        self.limit = limit
        self.buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        self.saved = 0
        self.truncated = Event()
        self.failed = Event()
        self.lock = Lock()
        self.threads = []

    def _read(self, name, stream):
        try:
            while chunk := stream.read(1024):
                with self.lock:
                    room = self.limit - self.saved
                    selected = chunk[:room]
                    self.buffers[name].extend(selected)
                    self.saved += len(selected)
                    if len(chunk) > room:
                        self.truncated.set()
        except OSError:
            self.failed.set()
        finally:
            try:
                stream.close()
            except OSError:
                self.failed.set()

    def start(self, process):
        for name in ('stdout', 'stderr'):
            # Daemon is only an escape hatch for unconfirmed OS cleanup, reported
            # as cleanup_failed. The normal path joins BOTH readers before return.
            thread = Thread(target=self._read, args=(name, getattr(process, name)), daemon=True)
            thread.start()
            self.threads.append(thread)

    def joined(self, deadline):
        for thread in self.threads:
            thread.join(max(0, deadline - monotonic()))
        return all(not thread.is_alive() for thread in self.threads)

    def text(self, name):
        with self.lock:
            # Invalid/incomplete UTF-8 is discarded; it must not expand a raw-byte
            # budget into longer replacement characters. captured_bytes is raw.
            return bytes(self.buffers[name]).decode('utf-8', errors='ignore')


class ControlledTestRunner:
    """Trusted host owns root, executable and limits; no model-callable tool."""
    def __init__(self, root: str | Path, *, limits: RunnerLimits | None = None):
        with files._filesystem_errors():
            self._root = files._canonical_root(root)
        if limits is not None and not isinstance(limits, RunnerLimits):
            raise ValueError('limits must be host-supplied RunnerLimits')
        self._limits = limits or RunnerLimits()
        self._python = str(Path(sys.executable).resolve(strict=True))
        self._unhealthy = False
        self._busy = Lock()

    @property
    def test_argv(self) -> tuple[str, ...]:
        """Reserved host template; unavailable until a sandbox backend exists."""
        return (self._python, *TEST_ARGUMENTS)

    def _prepare(self, name, scope) -> _Prepared:
        if self._unhealthy:
            raise _Blocked('cleanup_unconfirmed', 'previous process cleanup is unconfirmed; host intervention required')
        with files._filesystem_errors():
            if files._canonical_root(self._root) != self._root:
                raise _Blocked('invalid_cwd', 'working directory identity changed')
        if not Path(self._python).is_file() or not os.access(self._python, os.X_OK):
            raise _Blocked('permission_denied', 'trusted Python executable is unavailable or not executable')
        if scope == 'repository':
            if name != 'unittest':
                raise ValueError('only the fixed unittest template is allowed')
            # Fixed argv alone cannot authorize executing arbitrary repository code.
            inspect_environment()
            raise _Blocked('isolation_unavailable', 'no verified filesystem/network sandbox backend is configured')
        argv = probe_argv(self._python, name)
        if not inspect_environment().job_objects:
            raise _Blocked('process_control_unavailable', 'Windows Job/resource controls are unavailable')
        return _Prepared(argv, self._root, child_environment(self._root), scope)

    def run_tests(self, template: str = 'unittest') -> RunCommandResult:
        """Repository entry: fail closed; no unsafe host fallback/approval flag."""
        return self._run(template, 'repository')

    def run_probe(self, name: str) -> RunCommandResult:
        """Explicit trusted-host diagnostics, not repository or sandbox tests."""
        return self._run(name, 'trusted_fixed_probe')

    def _start(self, prepared):
        job, process = None, None
        try:
            job = WindowsJob()
            process = subprocess.Popen(list(prepared.argv), cwd=prepared.cwd, env=prepared.env,
                                       shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, bufsize=0, close_fds=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            job.assign(process.pid)
            # Fixed Python bootstrap waits here; no probe/child runs before assign.
            if process.stdin.write(b'GO\n') != 3:
                raise OSError('incomplete gate write')
            process.stdin.close()
            return process, job
        except OSError as exc:
            confirmed = True
            if process is not None:
                try:
                    process.kill()
                    process.wait(timeout=self._limits.cleanup_ms / 1000)
                except (OSError, subprocess.TimeoutExpired):
                    confirmed = False
                for stream in (process.stdin, process.stdout, process.stderr):
                    try:
                        stream.close()
                    except OSError:
                        confirmed = False
            if job is not None:
                try:
                    job.terminate()
                    deadline = monotonic() + self._limits.cleanup_ms / 1000
                    while job.active_processes() and monotonic() < deadline:
                        sleep(0.005)
                    confirmed = confirmed and job.active_processes() == 0
                except OSError:
                    confirmed = False
                finally:
                    try:
                        job.close()
                    except OSError:
                        confirmed = False
            raise _StartFailure(process is not None, confirmed) from exc

    def _observe(self, process, job, capture, deadline):
        root_exit_observed = None
        while True:
            if capture.truncated.is_set():
                return 'output_limit'
            if capture.failed.is_set():
                return 'output_read_failed'
            if process.poll() is not None:
                if root_exit_observed is None:
                    root_exit_observed = monotonic()
                active = job.active_processes()
                # Windows may signal root exit before Job accounting catches up.
                # Give accounting a bounded settling window inside the deadline.
                if active > 0 and monotonic() - root_exit_observed >= 0.05:
                    return 'descendants_remaining'
                if active == 0 and all(not thread.is_alive() for thread in capture.threads):
                    return 'completed'
            if monotonic() >= deadline:
                return 'timed_out'
            sleep(0.005)

    def _finish(self, process, job, capture, reason, started, scope):
        deadline = monotonic() + self._limits.cleanup_ms / 1000
        confirmed, active, cleanup_error = False, None, False
        members = []
        try:
            members = job.member_handles()
        except OSError:
            cleanup_error = True
        try:
            if job.active_processes() > 0:
                job.terminate()
        except OSError:
            cleanup_error = True
            try:
                process.kill()  # Root-only fallback is NOT proof that descendants stopped.
            except OSError:
                pass
        try:
            process.wait(timeout=max(0.001, deadline - monotonic()))
            while not cleanup_error and monotonic() < deadline:
                active = job.active_processes()
                if active == 0:
                    confirmed = True
                    break
                sleep(0.005)
        except (OSError, subprocess.TimeoutExpired):
            cleanup_error = True
        try:
            job.close()  # Kill-on-close is a final safeguard, not extra stop evidence.
        except OSError:
            cleanup_error = True
        members_stopped = job.wait_members(members, max(0, int((deadline - monotonic()) * 1000)))
        confirmed = confirmed and members_stopped
        # Closing a failed Job before joining allows kill-on-close to release the
        # child's pipe handles. Do not claim confirmation without accounting.
        joined = capture.joined(deadline)
        status = reason
        error = None
        if not confirmed or not joined or cleanup_error:
            self._unhealthy = True
            status = 'cleanup_failed'
            error = ToolError('cleanup_unconfirmed', 'process tree or reader cleanup could not be confirmed')
        elif reason != 'completed':
            error = ToolError(reason, 'controlled execution stopped: ' + reason)
        elif process.returncode != 0:
            status = 'failed'
            error = ToolError('nonzero_exit', 'process exited with a nonzero code')
        return RunCommandResult(process.returncode, reason == 'timed_out', capture.truncated.is_set(),
                                capture.text('stdout'), capture.text('stderr'),
                                int((monotonic() - started) * 1000), status, True, confirmed,
                                joined and confirmed and not cleanup_error, capture.saved, active, scope, error)

    def _run(self, name, scope):
        # A runner has one managed task at a time; unknown cleanup blocks reuse.
        with self._busy:
            started = monotonic()
            try:
                prepared = self._prepare(name, scope)
            except (_Blocked, files.FileAccessError) as exc:
                return RunCommandResult(None, False, False, '', '', int((monotonic() - started) * 1000),
                                        'blocked', scope=scope, error=ToolError(exc.code, str(exc)))
            try:
                process, job = self._start(prepared)
            except _StartFailure as exc:
                self._unhealthy = not exc.confirmed
                return RunCommandResult(None, False, False, '', '', int((monotonic() - started) * 1000),
                                        'start_failed', started=exc.started, termination_confirmed=exc.confirmed,
                                        cleanup_confirmed=exc.confirmed, scope=scope,
                                        error=ToolError('start_failed', 'process/Job setup failed'))
            capture = _OutputCapture(self._limits.max_output_bytes)
            reason = 'observation_failed'
            try:
                capture.start(process)
                reason = self._observe(process, job, capture, started + self._limits.timeout_ms / 1000)
            except OSError:
                reason = 'observation_failed'
            finally:
                result = self._finish(process, job, capture, reason, started, scope)
            return result

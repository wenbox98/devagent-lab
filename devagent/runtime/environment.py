"""Inspect actual local capabilities; there is no verified sandbox backend yet."""
import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import platform
from shutil import which
from tempfile import TemporaryDirectory

from .windows_job import WindowsJob


@dataclass(frozen=True)
class ExecutionCapabilities:
    platform: str
    job_objects: bool
    resource_limits: dict
    filesystem_isolation: bool = False
    network_isolation: bool = False
    repository_execution: bool = False
    reason: str = 'no verified filesystem/network sandbox backend is configured'


def inspect_environment() -> ExecutionCapabilities:
    """Create/query an empty Job; this does not prove filesystem isolation."""
    try:
        job = WindowsJob()
        try:
            limits = job.limits()
            valid = (limits['flags'] == WindowsJob.FLAGS and limits['max_processes'] == 4
                     and limits['process_memory_bytes'] == 128 * 1024 * 1024
                     and limits['job_memory_bytes'] == 256 * 1024 * 1024
                     and limits['job_cpu_100ns'] == 10 * 10_000_000)
        finally:
            job.close()
    except OSError:
        return ExecutionCapabilities(platform.system(), False, {}, reason='Windows Job setup/query unavailable')
    return ExecutionCapabilities(platform.system(), valid, limits)


def child_environment(root: Path) -> dict[str, str]:
    """Only Windows OS roots plus task-owned temp and fixed encoding settings.

    No PATH, HOME, PYTHONPATH, credentials, proxy or user environment inheritance.
    -I further prevents Python cwd/user-site imports; it is not a sandbox.
    """
    result = {key: os.environ[key] for key in ('SYSTEMROOT', 'WINDIR') if key in os.environ}
    result.update(TEMP=str(root), TMP=str(root), PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--trusted-probes', action='store_true',
                        help='Run fixed host probes only; never repository code or an isolation claim')
    args = parser.parse_args()
    capability = inspect_environment()
    report = {'capabilities': asdict(capability),
              'discovered_commands': {name: bool(which(name)) for name in ('docker', 'podman', 'wsl', 'WindowsSandbox.exe')},
              'blocked': {'code': 'isolation_unavailable', 'reason': capability.reason},
              'repository_execution_verified': False}
    if args.trusted_probes:
        from .runner import ControlledTestRunner, RunnerLimits
        with TemporaryDirectory() as directory:
            runner = ControlledTestRunner(directory, limits=RunnerLimits(timeout_ms=1000, max_output_bytes=4096))
            report['trusted_probe_results'] = {name: asdict(runner.run_probe(name))
                                               for name in ('normal', 'timeout', 'output-limit')}
        report['probe_scope'] = 'fixed trusted host programs; not repository/sandbox verification'
    print(json.dumps(report, ensure_ascii=True))
    return 2  # No sandbox is implemented/verified, even if Job lifecycle works.


if __name__ == '__main__':
    raise SystemExit(main())

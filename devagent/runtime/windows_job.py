"""Windows Job Object accounting/termination, not filesystem/network isolation.

API layouts follow Microsoft JOBOBJECT_* documentation. Only ordinary child
process creation is covered; this module does not create a security sandbox.
"""
import ctypes as ct
from ctypes import wintypes as wt
import os
from time import monotonic


class _BasicLimits(ct.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ct.c_longlong), ('PerJobUserTimeLimit', ct.c_longlong),
                ('LimitFlags', wt.DWORD), ('MinimumWorkingSetSize', ct.c_size_t),
                ('MaximumWorkingSetSize', ct.c_size_t), ('ActiveProcessLimit', wt.DWORD),
                ('Affinity', ct.c_size_t), ('PriorityClass', wt.DWORD), ('SchedulingClass', wt.DWORD)]


class _IoCounters(ct.Structure):
    _fields_ = [(name, ct.c_ulonglong) for name in
                ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class _ExtendedLimits(ct.Structure):
    _fields_ = [('BasicLimitInformation', _BasicLimits), ('IoInfo', _IoCounters),
                ('ProcessMemoryLimit', ct.c_size_t), ('JobMemoryLimit', ct.c_size_t),
                ('PeakProcessMemoryUsed', ct.c_size_t), ('PeakJobMemoryUsed', ct.c_size_t)]


class _Accounting(ct.Structure):
    _fields_ = [(name, ct.c_longlong) for name in ('TotalUserTime', 'TotalKernelTime',
                'ThisPeriodTotalUserTime', 'ThisPeriodTotalKernelTime')] + [
                (name, wt.DWORD) for name in ('TotalPageFaultCount', 'TotalProcesses',
                                            'ActiveProcesses', 'TotalTerminatedProcesses')]


class _ProcessIds(ct.Structure):
    # ActiveProcessLimit is fixed at 4; QueryInformationJobObject uses this array.
    _fields_ = [('NumberOfAssignedProcesses', wt.DWORD), ('NumberOfProcessIdsInList', wt.DWORD),
                ('ProcessIdList', ct.c_size_t * 4)]


class WindowsJob:
    """One owned handle. No breakaway flags; kill all members on last close."""
    FLAGS = 0x2000 | 0x0008 | 0x0100 | 0x0200 | 0x0004

    def __init__(self):
        if os.name != 'nt':
            raise OSError('Windows Job Objects are unavailable on this platform')
        self.api = ct.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateJobObjectW': ([ct.c_void_p, wt.LPCWSTR], wt.HANDLE),
            'SetInformationJobObject': ([wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD], wt.BOOL),
            'QueryInformationJobObject': ([wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD, ct.c_void_p], wt.BOOL),
            'OpenProcess': ([wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE),
            'AssignProcessToJobObject': ([wt.HANDLE, wt.HANDLE], wt.BOOL),
            'TerminateJobObject': ([wt.HANDLE, wt.UINT], wt.BOOL),
            'WaitForSingleObject': ([wt.HANDLE, wt.DWORD], wt.DWORD),
            'CloseHandle': ([wt.HANDLE], wt.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ct.WinError(ct.get_last_error())
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = self.FLAGS
        limits.BasicLimitInformation.ActiveProcessLimit = 4
        limits.BasicLimitInformation.PerJobUserTimeLimit = 10 * 10_000_000
        limits.ProcessMemoryLimit = 128 * 1024 * 1024
        limits.JobMemoryLimit = 256 * 1024 * 1024
        try:
            self._check(self.api.SetInformationJobObject(self.handle, 9, ct.byref(limits), ct.sizeof(limits)))
        except OSError:
            self.close()
            raise

    @staticmethod
    def _check(value):
        if not value:
            raise ct.WinError(ct.get_last_error())

    def assign(self, pid: int):
        # PROCESS_SET_QUOTA | PROCESS_TERMINATE, required by AssignProcessToJobObject.
        process = self.api.OpenProcess(0x0100 | 0x0001, False, pid)
        self._check(process)
        try:
            self._check(self.api.AssignProcessToJobObject(self.handle, process))
        finally:
            self._check(self.api.CloseHandle(process))

    def active_processes(self) -> int:
        info = _Accounting()
        self._check(self.api.QueryInformationJobObject(self.handle, 1, ct.byref(info), ct.sizeof(info), None))
        return info.ActiveProcesses

    def limits(self) -> dict:
        info = _ExtendedLimits()
        self._check(self.api.QueryInformationJobObject(self.handle, 9, ct.byref(info), ct.sizeof(info), None))
        return {'flags': info.BasicLimitInformation.LimitFlags,
                'max_processes': info.BasicLimitInformation.ActiveProcessLimit,
                'process_memory_bytes': info.ProcessMemoryLimit, 'job_memory_bytes': info.JobMemoryLimit,
                'job_cpu_100ns': info.BasicLimitInformation.PerJobUserTimeLimit}

    def terminate(self):
        self._check(self.api.TerminateJobObject(self.handle, 1))

    def member_handles(self) -> list:
        """Hold process identities BEFORE termination for actual exit waits."""
        info = _ProcessIds()
        self._check(self.api.QueryInformationJobObject(self.handle, 3, ct.byref(info), ct.sizeof(info), None))
        handles = []
        try:
            for pid in info.ProcessIdList[:info.NumberOfProcessIdsInList]:
                handle = self.api.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
                if not handle:
                    if ct.get_last_error() == 87:  # Process already disappeared.
                        continue
                    raise ct.WinError(ct.get_last_error())
                handles.append(handle)
            return handles
        except OSError:
            for handle in handles:
                self.api.CloseHandle(handle)
            raise

    def wait_members(self, handles: list, timeout_ms: int) -> bool:
        deadline = monotonic() + timeout_ms / 1000
        stopped = True
        try:
            for handle in handles:
                remaining = max(0, int((deadline - monotonic()) * 1000))
                if self.api.WaitForSingleObject(handle, remaining) != 0:
                    stopped = False
        finally:
            for handle in handles:
                if not self.api.CloseHandle(handle):
                    stopped = False
        return stopped

    def close(self):
        if self.handle:
            self._check(self.api.CloseHandle(self.handle))
            self.handle = None

"""Bound one authorized Windows process tree; explicit budgets, owned cleanup only."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


class BasicLimits(c.Structure):
    _fields_ = [('per_process_time', c.c_longlong), ('per_job_time', c.c_longlong),
                ('flags', w.DWORD), ('min_working', c.c_size_t), ('max_working', c.c_size_t),
                ('active_limit', w.DWORD), ('affinity', c.c_size_t),
                ('priority', w.DWORD), ('scheduling', w.DWORD)]

class ExtendedLimits(c.Structure):
    _fields_ = [('basic', BasicLimits), ('io', c.c_ulonglong * 6),
                ('process_memory', c.c_size_t), ('job_memory', c.c_size_t),
                ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--name', required=True)
    p.add_argument('--cwd', required=True, type=Path)
    p.add_argument('--timeout', type=float, required=True)
    p.add_argument('--run-root', type=Path, required=True)
    p.add_argument('--runner', type=Path, required=True)
    p.add_argument('--cores', type=int, required=True)
    p.add_argument('--memory-mb', type=int, required=True)
    p.add_argument('argv', nargs=argparse.REMAINDER)
    a = p.parse_args()
    if not a.name.replace('-', '').replace('_', '').isalnum():
        raise ValueError('Stage name must be an identifier')
    argv = a.argv[1:] if a.argv[:1] == ['--'] else a.argv
    if not argv or not 0 < a.timeout < float('inf') or a.memory_mb <= 0 or a.cores <= 0:
        raise ValueError('Invalid command or resource bound')
    root=a.run_root.resolve(strict=True);runner_path=a.runner.resolve(strict=True)
    if not a.cwd.resolve().is_relative_to(root):
        raise ValueError('Child cwd must stay in this run root')
    logs = root / 'resource-records'; logs.mkdir(exist_ok=True)
    record_path = logs / (a.name + '.json')
    if record_path.exists():
        raise ValueError('Stage record already exists; use new name')
    lock_path = root / '.resource-lock'
    lock = lock_path.open('x', encoding='utf8')
    lock.write(str(os.getpid())); lock.flush()
    job = child = None
    record = {'stage': a.name, 'argv': argv, 'cwd': str(a.cwd.resolve()),
              'memory_limit_bytes': a.memory_mb * 1024**2, 'timeout_seconds': a.timeout,
              'status': 'launch_failed', 'started_ns': time.time_ns()}
    code = 1
    try:
        spec = importlib.util.spec_from_file_location('bounded_runner', runner_path)
        runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
        job = runner.WindowsJob()
        job.api.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        job.api.SetInformationJobObject.restype = w.BOOL
        job.api.GetCurrentProcess.restype = w.HANDLE
        job.api.GetProcessAffinityMask.argtypes = [w.HANDLE, c.POINTER(c.c_size_t), c.POINTER(c.c_size_t)]
        job.api.GetProcessAffinityMask.restype = w.BOOL
        allowed, system = c.c_size_t(), c.c_size_t()
        if not job.api.GetProcessAffinityMask(job.api.GetCurrentProcess(), c.byref(allowed), c.byref(system)):
            raise c.WinError(c.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x10 | 0x200 | 0x2000  # AFFINITY, JOB_MEMORY, KILL_ON_CLOSE
        available=[1<<i for i in range(allowed.value.bit_length()) if allowed.value & (1<<i)]
        if a.cores>len(available):raise ValueError('CPU budget exceeds available affinity')
        limits.basic.affinity = sum(available[:a.cores])
        limits.job_memory = record['memory_limit_bytes']
        if not job.api.SetInformationJobObject(job.handle, 9, c.byref(limits), c.sizeof(limits)):
            raise c.WinError(c.get_last_error())
        record['affinity_mask'] = limits.basic.affinity
        env = os.environ.copy()
        env.update(OMP_NUM_THREADS=str(a.cores), MKL_NUM_THREADS=str(a.cores), OPENBLAS_NUM_THREADS=str(a.cores),
                   PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
        # os.environ.copy() is a regular dict: on Windows its key may be
        # PSMODULEPATH. Let each PowerShell host construct its own module paths.
        env = {key: value for key, value in env.items() if key.casefold() != 'psmodulepath'}
        with (logs / (a.name + '.stdout.log')).open('xb') as out, (logs / (a.name + '.stderr.log')).open('xb') as err:
            child = subprocess.Popen(argv, cwd=a.cwd, env=env, shell=False, stdin=subprocess.DEVNULL,
                stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | 4)
            record['pid'] = child.pid
            job.attach_and_resume(child)
            try:
                code = child.wait(timeout=a.timeout)
                record.update(status='exited', exit_code=code)
                if not job.wait_empty(2):
                    record['status'] = 'descendants_remaining'; job.stop(); code = 125
            except subprocess.TimeoutExpired:
                job.stop(); child.wait(timeout=15); code = 124
                record.update(status='timed_out', exit_code=child.returncode)
        observed = ExtendedLimits()
        if job.api.QueryInformationJobObject(job.handle, 9, c.byref(observed), c.sizeof(observed), None):
            record.update(peak_job_memory_bytes=observed.peak_job, peak_process_memory_bytes=observed.peak_process)
        record['remaining_owned_processes'] = job.active()
    except BaseException as exc:
        code = 125
        record['status'] = 'guard_failed'
        record['error'] = str(exc)
        if child is not None:
            if job and job.attached:
                job.stop()
            elif child.poll() is None:
                child.kill()
            child.wait(timeout=15)
    finally:
        if job: job.close()
        record['finished_ns'] = time.time_ns()
        record['elapsed_seconds'] = round((record['finished_ns'] - record['started_ns']) / 1e9, 3)
        with record_path.open('x', encoding='utf8') as out:
            json.dump(record, out, ensure_ascii=False, indent=2)
        lock.close(); lock_path.unlink()
    print(json.dumps(record, ensure_ascii=False))
    return code

if __name__ == '__main__':
    raise SystemExit(main())

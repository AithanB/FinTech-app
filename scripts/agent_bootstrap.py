"""Runs inside the data-free jail, after chroot and UID/capability drop."""

import ctypes
import errno
import runpy


lib = ctypes.CDLL("libseccomp.so.2")
lib.seccomp_init.argtypes = [ctypes.c_uint32]
lib.seccomp_init.restype = ctypes.c_void_p
lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
lib.seccomp_load.argtypes = [ctypes.c_void_p]
lib.seccomp_release.argtypes = [ctypes.c_void_p]
context = lib.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
if not context:
    raise RuntimeError("sandbox setup failed")
try:
    # No processes, network, process inspection or namespace escape. Default
    # runtime syscalls remain available for ordinary Python decimal/JSON tools.
    blocked = (
        "clone", "clone3", "fork", "vfork", "execve", "execveat", "setsid", "setpgid",
        "socket", "socketpair", "connect", "bind", "listen", "accept", "accept4",
        "ptrace", "process_vm_readv", "process_vm_writev", "pidfd_getfd", "pidfd_open",
        "kill", "tkill", "tgkill", "pidfd_send_signal", "mount", "umount2", "pivot_root",
        "chroot", "unshare", "setns", "bpf", "userfaultfd", "io_uring_setup",
        "open_by_handle_at", "name_to_handle_at", "keyctl", "add_key", "request_key",
    )
    for name in blocked:
        number = lib.seccomp_syscall_resolve_name(name.encode())
        if number >= 0 and lib.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0) != 0:
            raise RuntimeError("sandbox rule failed")
    if lib.seccomp_load(context) != 0:
        raise RuntimeError("sandbox load failed")
finally:
    lib.seccomp_release(context)

runpy.run_path("/policy.py", run_name="__main__")

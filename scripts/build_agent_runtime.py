"""Build an immutable, data-free Python root for chroot (Linux image build)."""

import ctypes.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig


def build(destination):
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)

    def copy(path):
        target = root / str(path).lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target, follow_symlinks=True)

    executable = Path(sys.executable).resolve()
    copy(executable)
    stdlib = Path(sysconfig.get_path("stdlib"))
    shutil.copytree(stdlib, root / str(stdlib).lstrip("/"), ignore=shutil.ignore_patterns(
        "site-packages", "__pycache__", "ensurepip", "idlelib", "tkinter", "turtledemo", "test", "tests",
    ))
    # Public IANA timezone rules are needed by policies applying the manifest's
    # timezone, including DST. No evaluator files or host configuration enter.
    shutil.copytree("/usr/share/zoneinfo", root / "usr/share/zoneinfo")
    # Include every dependency of the interpreter and extension modules, at the
    # loader's original absolute location. No shell expansion or host mounts.
    libraries = [executable, *stdlib.glob("lib-dynload/*.so")]
    seccomp = ctypes.util.find_library("seccomp")
    if seccomp is None:
        raise RuntimeError("libseccomp2 required")
    listing = subprocess.check_output(["ldconfig", "-p"], text=True)
    seccomp_path = next(line.split("=>", 1)[1].strip() for line in listing.splitlines() if seccomp in line)
    libraries.append(Path(seccomp_path))
    copy(seccomp_path)
    for library in libraries:
        linked = subprocess.run(["ldd", str(library)], capture_output=True, text=True, check=True).stdout
        for path in re.findall(r"(?:=>\s+)?(/[^\s]+)", linked):
            copy(path)
    shutil.copy2(Path(__file__).with_name("agent_bootstrap.py"), root / "bootstrap.py")
    # Template is root-owned and cannot be modified by the policy identity.
    for directory, dirs, files in os.walk(root):
        Path(directory).chmod(0o755)
        for name in files:
            target = Path(directory) / name
            target.chmod(0o555 if os.access(target, os.X_OK) else 0o444)


if __name__ == "__main__":
    build(sys.argv[1])

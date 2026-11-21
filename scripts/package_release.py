"""Deterministic source/evidence ZIP with an exact SHA-256 inventory.

Does not use Git's index: all selected current source, including untracked stage
work, is included. Omits secrets, local environments, caches and artifact output.
The prepared image is a separate delivery file, not nested in its own context.
"""

import argparse
import hashlib
import json
from pathlib import Path
import stat
import zipfile


ROOT = Path(__file__).resolve().parent.parent
DIRECTORIES = ("audit_env", "policies", "configs", "tests", "scripts", "docs", "episodes", "evaluator", "release")
FILES = ("judge_adapter.py", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "Dockerfile", "requirements.txt", "requirements.in",
         "pytest.ini", ".gitignore", ".gitattributes", ".dockerignore")
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", "artifacts", ".git", ".venv", ".codex", ".agents", ".aws", "runs"}
MANIFEST = "release/payload-manifest.json"


def payload(root=ROOT):
    root = Path(root).resolve()
    paths = [root / name for name in FILES]
    for directory in DIRECTORIES:
        paths.extend((root / directory).rglob("*"))
    result = {}
    for path in sorted(set(paths)):
        relative = path.relative_to(root)
        if any(part in EXCLUDE_PARTS for part in relative.parts) or relative.as_posix() == MANIFEST:
            continue
        if path.is_symlink():
            raise ValueError(f"symlinks are not allowed in release: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"required release file missing: {relative}")
        if path.suffix in (".pyc", ".pyo") or path.name.startswith(".env"):
            continue
        # Canonical text bytes survive Windows checkout newline conventions.
        data = path.read_bytes()
        if b"\0" not in data:
            data = data.replace(b"\r\n", b"\n")
        result[relative.as_posix()] = data
    for split in ("train", "dev"):
        manifests = [name for name in result if name.startswith(f"episodes/{split}/") and name.endswith("/manifest.json")]
        if len(manifests) != 10:
            raise ValueError(f"release needs exactly ten {split} episodes")
    required = ("evaluator/stage11/results.json", "evaluator/stage11/paired-checks.json",
                "evaluator/stage12/demo/demo.json", "release/image-lock.json", "release/dependency-lock.json",
                "release/schemas/Action.schema.json", "release/licenses/Python-LICENSE.txt",
                "docs/stage-12.md", "docs/design.md", "docs/demo.md")
    for name in required:
        if name not in result:
            raise ValueError(f"required release evidence missing: {name}")
    return result


def build_archive(destination, root=ROOT):
    destination = Path(destination)
    if destination.exists():
        raise ValueError("archive destination already exists")
    content = payload(root)
    manifest = {"version": "stage12-payload-v1", "files": {
        name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in content.items()}}
    content[MANIFEST] = (json.dumps(manifest, indent=2) + "\n").encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(content.items()):
            item = zipfile.ZipInfo("audit-rl-env/" + name, date_time=(2026, 11, 21, 0, 0, 0))
            item.create_system = 3
            item.external_attr = (stat.S_IFREG | 0o644) << 16
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return {"file": destination.name, "bytes": destination.stat().st_size,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "payload_files": len(content)}


def check_archive(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(not name.startswith("audit-rl-env/") or ".." in Path(name).parts for name in names):
            raise ValueError("unsafe or duplicate archive paths")
        manifest_name = "audit-rl-env/" + MANIFEST
        manifest = json.loads(archive.read(manifest_name))
        expected = {"audit-rl-env/" + name for name in manifest["files"]} | {manifest_name}
        if set(names) != expected:
            raise ValueError("archive inventory mismatch")
        for name, row in manifest["files"].items():
            if ".." in Path(name).parts or Path(name).is_absolute():
                raise ValueError("unsafe manifest path")
            data = archive.read("audit-rl-env/" + name)
            if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError(f"archive digest mismatch: {name}")
        return {"checked": True, "payload_files": len(names)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    if bool(args.output) == bool(args.check):
        parser.error("choose --output PATH or --check ZIP")
    try:
        print(json.dumps(check_archive(args.check) if args.check else build_archive(args.output)))
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"packaging failed: {exc}\n")


if __name__ == "__main__":
    main()

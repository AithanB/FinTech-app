"""Release payload integrity and the actual three-case isolated demo."""

import json
import zipfile

import pytest

from audit_env.demo import run_demo
from scripts.package_release import FILES, build_archive, check_archive, payload
from test_stage05 import require_linux


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    for name in FILES:
        (root / name).write_bytes(b"source\r\n")
    for split in ("train", "dev"):
        for index in range(10):
            directory = root / "episodes" / split / f"opaque-{split}-{index}"
            directory.mkdir(parents=True)
            (directory / "manifest.json").write_text("{}\n")
    for name in ("evaluator/stage11/results.json", "evaluator/stage11/paired-checks.json",
                 "evaluator/stage12/demo/demo.json", "release/image-lock.json", "release/dependency-lock.json",
                 "release/schemas/Action.schema.json", "release/licenses/Python-LICENSE.txt",
                 "docs/stage-12.md", "docs/design.md", "docs/demo.md"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")
    return root


def test_payload_is_deterministic_includes_untracked_files_and_excludes_local_data(source, tmp_path):
    for name in ("runs/private.txt", ".git/private.txt", ".env", "release/artifacts/image.tar",
                 "audit_env/__pycache__/private.pyc", "configs/.env.local"):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("must-not-ship")
    (source / "audit_env/new_untracked.py").write_text("print('synthetic')\n")
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    a = build_archive(first, source)
    b = build_archive(second, source)
    assert first.read_bytes() == second.read_bytes() and a["sha256"] == b["sha256"]
    assert check_archive(first)["checked"]
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert "audit-rl-env/audit_env/new_untracked.py" in names
        assert archive.read("audit-rl-env/README.md") == b"source\n"
        assert all(b"must-not-ship" not in archive.read(name) for name in names)
    with pytest.raises(ValueError, match="already exists"):
        build_archive(first, source)


@pytest.mark.parametrize("missing", ["LICENSE", "episodes/dev/opaque-dev-9/manifest.json", "evaluator/stage12/demo/demo.json"])
def test_release_refuses_missing_deliverables(source, missing):
    (source / missing).unlink()
    with pytest.raises(ValueError):
        payload(source)


def test_archive_checker_rejects_corrupted_content_and_traversal(source, tmp_path):
    original = tmp_path / "original.zip"
    build_archive(original, source)
    corrupt = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(original) as reader, zipfile.ZipFile(corrupt, "w") as writer:
        for name in reader.namelist():
            writer.writestr(name, b"changed" if name.endswith("/LICENSE") else reader.read(name))
    with pytest.raises(ValueError, match="digest"):
        check_archive(corrupt)
    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("audit-rl-env/../escape", "bad")
    with pytest.raises(ValueError, match="unsafe"):
        check_archive(unsafe)


def test_linux_three_case_demo_has_supported_clean_and_single_false_accusation(tmp_path):
    require_linux()
    result = run_demo(tmp_path / "demo")
    assert result["passed"]
    assert [(r["tp"], r["fp"], r["fn"], r["return"], r["total_actions"]) for r in result["cases"]] == [
        (1, 0, 0, .992, 5), (0, 0, 0, .992, 5), (0, 1, 0, -1, 2),
    ]
    for row in result["cases"]:
        trace = [json.loads(line) for line in (tmp_path / "demo" / row["trajectory"]).read_text().splitlines()]
        assert all(event["reward"] == 0 for event in trace[1:])
        assert trace[-1]["terminated"] and not trace[-1]["truncated"]
    with pytest.raises(ValueError, match="empty or new"):
        run_demo(tmp_path / "demo")

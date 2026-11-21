"""Export open schemas, exact installed versions and bundled license notices."""

import argparse
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess

from pydantic import TypeAdapter
from audit_env import schemas


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def export(output):
    output = Path(output)
    for name in ("Manifest", "Policy", "LedgerRow", "Invoice", "Payment", "FXRow", "Settlement", "PublicEpisode",
                 "Submission", "Truth", "Provenance", "RecordPage", "ErrorReply"):
        write_json(output / "schemas" / f"{name}.schema.json", getattr(schemas, name).model_json_schema())
    write_json(output / "schemas/Action.schema.json", TypeAdapter(schemas.Action).json_schema())
    distributions = []
    for distribution in sorted(metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = distribution.metadata["Name"]
        notices = []
        for file in distribution.files or []:
            if any(token in Path(str(file)).name.lower() for token in ("license", "copying", "notice", "authors", "copyright")):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    target = output / "licenses/python" / name / str(file)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())
                    notices.append(target.relative_to(output).as_posix())
        distributions.append({"name": name, "version": distribution.version, "license_files": notices,
                              "license_expression": distribution.metadata.get("License-Expression")})
    for source_root, label in ((Path("/usr/share/doc"), "system"),
                               (Path("/opt/agent-runtime-licenses"), "agent-runtime")):
        for source in source_root.rglob("copyright"):
            if source.is_file():
                target = output / "licenses" / label / source.relative_to(source_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
    python_license = Path("/usr/local/lib/python3.11/LICENSE.txt")
    if not python_license.is_file():
        raise ValueError("Python license missing from prepared image")
    target = output / "licenses/Python-LICENSE.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(python_license.read_bytes())
    system = subprocess.check_output(["dpkg-query", "-W", "-f=${Package}\t${Version}\n"], text=True)
    runtime_versions = Path("/opt/agent-runtime-packages.txt")
    write_json(output / "dependency-lock.json", {"python": platform.python_version(), "python_distributions": distributions,
               "system_packages": system.splitlines(),
               "agent_runtime_builder_packages": runtime_versions.read_text().splitlines() if runtime_versions.is_file() else [],
               "os_release": Path("/etc/os-release").read_text()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    export(parser.parse_args().output)

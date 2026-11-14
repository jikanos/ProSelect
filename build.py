"""Build the Windows executable with its Git version embedded."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=("test", "analyzer"), nargs="?", default="test")
    args = parser.parse_args()
    project = Path(__file__).resolve().parent
    if args.target == "analyzer":
        script = project / "analyzer" / "ProSelectAnalyzer.py"
        assets = ()
    else:
        script = project / "ProSelect.py"
        assets = (project / "de-friz_logo.png", project / "questions.json")

    version = subprocess.check_output(
        ["git", "describe", "--tags", "--match", "v[0-9]*", "--always", "--dirty"],
        cwd=project,
        text=True,
    ).strip()
    build_dir = project / "build"
    build_dir.mkdir(exist_ok=True)
    version_file = build_dir / "build_version.json"
    version_file.write_text(json.dumps({"version": version}) + "\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.setdefault("PYINSTALLER_CONFIG_DIR", str(build_dir / "pyinstaller-cache"))
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
        "--specpath", "build", "--name", script.stem,
    ]
    for asset in (*assets, version_file):
        command.extend(("--add-data", f"{asset}:."))
    command.append(str(script))
    subprocess.run(command, cwd=project, env=environment, check=True)


if __name__ == "__main__":
    main()

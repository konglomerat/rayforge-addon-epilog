"""Validate using an existing Rayforge development environment."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--rayforge", type=Path, required=True)
args = parser.parse_args()
rayforge = args.rayforge.resolve()
root = Path(__file__).resolve().parent.parent
if not (rayforge / "tests/conftest.py").is_file():
    parser.error("--rayforge must point to a Rayforge source checkout")
env = os.environ.copy()
env["PYTHONPATH"] = os.pathsep.join([str(rayforge), str(root)])
commands = [
    ["ruff", "check", str(root)],
    ["ruff", "format", "--check", str(root)],
    ["pytest", "-p", "tests.conftest", str(root / "tests"), "--tb=short"],
]
for command in commands:
    subprocess.run(
        [sys.executable, "-m", *command],
        cwd=rayforge,
        env=env,
        check=True,
    )

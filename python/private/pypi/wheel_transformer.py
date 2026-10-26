# Copyright 2026 The Bazel Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Build-action wrapper to run a wheel transformation tool and output a .whldir TreeArtifact."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from wheel_layout import single_wheel_in  # noqa: E402

BAZEL_LAUNCHER_VARS = (
    "PYTHONSAFEPATH",
    "PYTHONPATH",
    "PYTHONHOME",
    "RUNFILES_DIR",
    "RUNFILES_MANIFEST_FILE",
    "RUNFILES_MANIFEST_ONLY",
)


def scrub_bazel_env(env: dict[str, str]) -> dict[str, str]:
    """Remove Bazel py_binary launcher variables from `env` in-place."""
    for key in BAZEL_LAUNCHER_VARS:
        env.pop(key, None)
    return env


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a wheel transform tool and collect the transformed wheel.",
        fromfile_prefix_chars="@",
    )
    parser.add_argument(
        "--wheel",
        type=Path,
        required=True,
        help="Path to the input .whl file or .whldir directory.",
    )
    parser.add_argument(
        "--out-wheel-dir",
        type=Path,
        required=True,
        help="Directory where the transform tool writes the output wheel.",
    )
    parser.add_argument(
        "--tool",
        required=True,
        help="Path to the user's transform tool executable.",
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        help="Extra environment variable in KEY=VALUE format (can be repeated).",
    )
    args = parser.parse_args()

    wheel_file = single_wheel_in(args.wheel) if args.wheel.is_dir() else args.wheel
    args.out_wheel_dir.mkdir(parents=True, exist_ok=True)

    env = scrub_bazel_env(dict(os.environ))
    env["WHEEL_FILE"] = str(wheel_file.absolute())
    env["WHEEL_OUTPUT_ROOT"] = str(args.out_wheel_dir.absolute())

    for env_entry in args.env:
        key, sep, value = env_entry.partition("=")
        if not sep or not key:
            raise ValueError(f"Invalid --env entry '{env_entry}', expected KEY=VALUE")
        env[key] = value

    subprocess.check_call([os.path.abspath(args.tool)], env=env)
    single_wheel_in(args.out_wheel_dir, check_stray=True)


if __name__ == "__main__":
    main()

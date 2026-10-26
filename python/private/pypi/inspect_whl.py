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

"""Inspect a wheel archive without extracting it to disk."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wheel_layout import (  # noqa: E402
    find_wheel_dist_info_and_entry_points,
    glob_to_regex,
    is_excluded,
    is_pkgutil_namespace_init,
    plan_wheel_entries,
)


def inspect_wheel(
    wheel_path: Path,
    srcs_exclude_globs: list[str] | None = None,
    data_exclude_globs: list[str] | None = None,
) -> dict[str, Any]:
    """Inspect a .whl zip file and return metadata and extracted file paths."""
    srcs_exclude_rx = [glob_to_regex(p) for p in (srcs_exclude_globs or ())]
    data_exclude_rx = [glob_to_regex(p) for p in (data_exclude_globs or ())]

    extracted_files: set[str] = set()
    namespace_package_files: set[str] = set()
    shebang_scripts: set[str] = set()

    with zipfile.ZipFile(wheel_path) as z:
        dist_info_dir, metadata_content, entry_points_content = (
            find_wheel_dist_info_and_entry_points(z)
        )
        for info, dest_or_script, is_shebang in plan_wheel_entries(
            z,
            dist_info_dir,
            entry_points_content,
            srcs_exclude_rx,
            data_exclude_rx,
        ):
            if is_shebang:
                shebang_scripts.add(dest_or_script)
                continue
            extracted_files.add(dest_or_script)
            if (
                dest_or_script.startswith("site-packages/")
                and dest_or_script.count("/") == 2
                and dest_or_script.endswith("/__init__.py")
                and dest_or_script.split("/")[1].isidentifier()
            ):
                content = z.read(info).decode("utf-8", "replace")
                if is_pkgutil_namespace_init(content):
                    namespace_package_files.add(dest_or_script)

    if dist_info_dir:
        installer_rel = f"site-packages/{dist_info_dir}/INSTALLER"
        if not is_excluded(installer_rel, data_exclude_rx):
            extracted_files.add(installer_rel)

    return {
        "entry_points_content": entry_points_content,
        "extracted_files": sorted(extracted_files),
        "metadata_content": metadata_content,
        "namespace_package_files": sorted(namespace_package_files),
        "shebang_scripts": sorted(shebang_scripts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a wheel file.")
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument(
        "--srcs-exclude-glob",
        action="append",
        dest="srcs_exclude_globs",
        default=[],
    )
    parser.add_argument(
        "--data-exclude-glob",
        action="append",
        dest="data_exclude_globs",
        default=[],
    )
    args = parser.parse_args()

    json.dump(
        inspect_wheel(args.wheel, args.srcs_exclude_globs, args.data_exclude_globs),
        sys.stdout,
        sort_keys=True,
    )


if __name__ == "__main__":
    main()

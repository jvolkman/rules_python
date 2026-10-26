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

"""Transform tool for testing py_wheel_transform."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path


def main() -> None:
    in_whl = Path(os.environ["WHEEL_FILE"])
    out_dir = Path(os.environ["WHEEL_OUTPUT_ROOT"])
    marker = Path(os.environ["DATA_MARKER_FILE"]).read_text(encoding="utf-8").strip()
    out_whl = out_dir / in_whl.name

    with zipfile.ZipFile(in_whl, "r") as zin, zipfile.ZipFile(out_whl, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "demo_pkg/__init__.py":
                text = data.decode("utf-8").replace(
                    "TRANSFORMED = False", f'TRANSFORMED = "{marker}"'
                )
                data = text.encode("utf-8")
            zout.writestr(item, data)


if __name__ == "__main__":
    main()

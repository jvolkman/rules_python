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

"""Provider for an installed wheel directory (TreeArtifact)."""

PyInstalledWheelInfo = provider(
    doc = "Information about an installed Python wheel TreeArtifact.",
    fields = {
        "directory": """
:type: File
The installed wheel TreeArtifact directory containing site-packages/, data/,
bin/, and include/.
""",
        "keep_source": """
:type: bool
Whether `.py` source files are retained in `directory`.
""",
        "precompiled": """
:type: bool
Whether `.py` files in `directory` were precompiled into `.pyc` files.
""",
        "settings_key": """
:type: tuple
Tuple of install settings `(should_precompile, keep_source, invalidation_mode,
optimize_level, srcs_exclude, data_exclude, create_namespace_inits)` used to
determine whether an outer `py_wheel_library` can reuse `directory`.
""",
        "wheel": """
:type: File | None
The underlying `.whl` file (or `.whldir` directory) when the installed wheel has
no `post_install_patches`, or `None` if `post_install_patches` were applied.
""",
    },
)

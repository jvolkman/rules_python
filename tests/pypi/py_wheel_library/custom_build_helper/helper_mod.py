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

"""First-party build helper module used to test py_library in py_sdist_wheel.build_deps."""

import os

with open(
    os.path.join(os.path.dirname(__file__), "helper_data.txt"),
    encoding="utf-8",
) as _f:
    HELPER_DATA = _f.read().strip()

HELPER_READY = HELPER_DATA == "helper_data_ok"

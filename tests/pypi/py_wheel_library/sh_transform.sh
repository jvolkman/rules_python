#!/usr/bin/env bash
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

set -euo pipefail

if [[ -z "${PATH:-}" ]]; then
  echo "ERROR: PATH is missing in sh_binary transform" >&2
  exit 1
fi
if [[ "${EXPECTED_SH_ENV:-}" != "from_transform" ]]; then
  echo "ERROR: EXPECTED_SH_ENV not forwarded: ${EXPECTED_SH_ENV:-}" >&2
  exit 1
fi
for var in RUNFILES_DIR RUNFILES_MANIFEST_FILE PYTHONSAFEPATH PYTHONPATH PYTHONHOME; do
  if [[ -n "${!var:-}" ]]; then
    echo "ERROR: wrapper ${var} leaked into sh_binary transform: ${!var}" >&2
    exit 1
  fi
done

if [[ "$(basename "${WHEEL_FILE}")" != *-*-*-*-*.whl ]]; then
  echo "ERROR: WHEEL_FILE basename is not a canonical PEP 427 wheel filename: $(basename "${WHEEL_FILE}")" >&2
  exit 1
fi
cp "${WHEEL_FILE}" "${WHEEL_OUTPUT_ROOT}/$(basename "${WHEEL_FILE}")"

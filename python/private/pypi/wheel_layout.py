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

"""Shared wheel layout mapping and path sanitization for inspect_whl and action_whl_installer."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path

BAZEL_REPO_FILES = frozenset(
    {
        "BUILD",
        "BUILD.bazel",
        "REPO.bazel",
        "WORKSPACE",
        "WORKSPACE.bazel",
        "WORKSPACE.bzlmod",
    }
)

DATA_CATEGORIES = {
    "data": "data",
    "headers": "include",
    "platlib": "site-packages",
    "purelib": "site-packages",
    "scripts": "bin",
}

INSTALLER_URL = "https://github.com/bazel-contrib/rules_python#pipstar"


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Convert a Bazel-style glob pattern (supporting `**`) into a compiled regex."""
    i = 0
    n = len(pattern)
    parts = ["^"]
    while i < n:
        if pattern[i : i + 3] == "**/":
            parts.append("(?:.+/)?")
            i += 3
        elif pattern[i : i + 3] == "/**":
            parts.append("(?:/.*)?")
            i += 3
        elif pattern[i : i + 2] == "**":
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1
    parts.append("$")
    return re.compile("".join(parts))


def is_excluded(path: str, compiled_globs: list[re.Pattern[str]]) -> bool:
    """Return whether `path` matches any compiled exclusion glob."""
    return any(rx.match(path) for rx in compiled_globs)


def is_pkgutil_namespace_init(content: str) -> bool:
    """Whether an `__init__.py` declares a pkgutil namespace package."""
    return (
        "__path__ =" in content and "pkgutil" in content and "extend_path(" in content
    )


def parse_entry_point_names_lower(contents: str) -> set[str]:
    """Parse lowercase console_scripts and gui_scripts names from entry_points.txt."""
    names: set[str] = set()
    current_group_lower = None
    for line in contents.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_group_lower = line[1:-1].strip().lower()
            continue
        if current_group_lower in ("console_scripts", "gui_scripts"):
            name, _, _ = line.partition("=")
            name = name.strip()
            if name:
                names.add(name.lower())
    return names


def sanitize_wheel_entry_path(name: str) -> list[str] | None:
    """Validate and split a wheel zip member path into normalized path components.

    Returns None for directory entries (`name.endswith("/")`).
    Raises ValueError if the path is absolute, contains backslashes, drive
    letters, empty segments, `.`, or `..`.
    """
    if name.endswith("/"):
        return None
    if name.startswith("/") or "\\" in name:
        raise ValueError(f"Unsafe wheel entry path: {name!r}")
    parts = name.split("/")
    if not parts or ":" in parts[0]:
        raise ValueError(f"Unsafe wheel entry path: {name!r}")
    for part in parts:
        if part in ("", ".", ".."):
            raise ValueError(f"Unsafe wheel entry path: {name!r}")
    return parts


def find_wheel_dist_info_and_entry_points(
    zf: zipfile.ZipFile,
) -> tuple[str, str, str]:
    """Return `(dist_info_dir, metadata_content, entry_points_content)` for `zf`."""
    dist_info_dir = ""
    metadata_content = ""
    entry_points_content = ""

    for info in zf.infolist():
        parts = sanitize_wheel_entry_path(info.filename)
        if parts is None:
            continue
        if len(parts) == 2 and parts[0].endswith(".dist-info"):
            if parts[1] == "METADATA" and not dist_info_dir:
                dist_info_dir = parts[0]
                metadata_content = zf.read(info).decode("utf-8", "replace")
            elif parts[1] == "entry_points.txt" and not entry_points_content:
                entry_points_content = zf.read(info).decode("utf-8", "replace")

    return dist_info_dir, metadata_content, entry_points_content


def expected_data_dir_for_dist_info(dist_info_dir: str) -> str:
    """Derive the PEP 427 `.data` directory name from the `.dist-info` directory name."""
    if dist_info_dir.endswith(".dist-info"):
        return dist_info_dir[: -len(".dist-info")] + ".data"
    return ""


def map_wheel_entry_destination(
    name: str,
    parts: list[str],
    expected_data_dir: str,
    seen_destinations: dict[str, str],
    *,
    wheel_dist_info_dir: str = "",
    target_dist_info_dir: str = "",
) -> str | None:
    """Map a wheel archive entry to its installed relative path under the TreeArtifact root.

    Raises ValueError if two distinct wheel entries map to the same destination path
    (e.g. a collision between purelib and platlib or root and `.data`).
    """
    if parts[-1] in BAZEL_REPO_FILES:
        return None

    if expected_data_dir and parts[0] == expected_data_dir:
        if len(parts) <= 2:
            return None
        dest_prefix = DATA_CATEGORIES.get(parts[1])
        if not dest_prefix:
            return None
        rel_path = "/".join(parts[2:])
        if not rel_path:
            return None
        dest_rel = f"{dest_prefix}/{rel_path}"
    elif (
        wheel_dist_info_dir
        and target_dist_info_dir
        and target_dist_info_dir != wheel_dist_info_dir
        and parts[0] == wheel_dist_info_dir
    ):
        dest_rel = f"site-packages/{target_dist_info_dir}/{'/'.join(parts[1:])}"
    else:
        dest_rel = f"site-packages/{name}"

    prev = seen_destinations.get(dest_rel)
    if prev is not None and prev != name:
        raise ValueError(
            f"Detected collision at '{dest_rel}' between wheel entries '{prev}' and '{name}'"
        )
    seen_destinations[dest_rel] = name
    return dest_rel


def plan_wheel_entries(
    zf: zipfile.ZipFile,
    dist_info_dir: str,
    entry_points_content: str,
    srcs_exclude_rx: list[re.Pattern[str]],
    data_exclude_rx: list[re.Pattern[str]],
    *,
    target_dist_info_dir: str = "",
) -> Iterator[tuple[zipfile.ZipInfo, str, bool]]:
    """Yield `(info, dest_rel_or_script_name, is_shebang_script)` for wheel entries."""
    expected_data_dir = expected_data_dir_for_dist_info(dist_info_dir)
    ep_names_lower = parse_entry_point_names_lower(entry_points_content)
    seen_destinations: dict[str, str] = {}

    for info in zf.infolist():
        name = info.filename
        parts = sanitize_wheel_entry_path(name)
        if parts is None:
            continue

        dest_rel = map_wheel_entry_destination(
            name,
            parts,
            expected_data_dir,
            seen_destinations,
            wheel_dist_info_dir=dist_info_dir,
            target_dist_info_dir=target_dist_info_dir,
        )
        if dest_rel is None:
            continue

        if dest_rel.startswith("site-packages/"):
            exclude_rx = (
                srcs_exclude_rx if dest_rel.endswith(".py") else data_exclude_rx
            )
            if is_excluded(dest_rel, exclude_rx):
                continue

        if dest_rel.startswith("bin/") and dest_rel.count("/") == 1:
            script_name = dest_rel[len("bin/") :]
            if script_name.lower() in ep_names_lower:
                continue
            if not script_name.endswith((".exe", ".dll")):
                with zf.open(info) as f:
                    head = f.read(10)
                if head.startswith(b"#!python"):
                    yield info, script_name, True
                    continue

        yield info, dest_rel, False


def create_namespace_inits(site_packages_dir: Path, init_content: str) -> None:
    """Populate pkgutil-style `__init__.py` files for implicit namespace packages."""
    if not site_packages_dir.is_dir():
        return

    all_rel_files = sorted(
        p.relative_to(site_packages_dir).as_posix()
        for p in site_packages_dir.rglob("*")
        if p.is_file()
    )

    dirs: dict[str, None] = {}
    ignored: dict[str, None] = {}

    def add_all(dirname: str, target: dict[str, None]) -> None:
        dir_path = "."
        for dir_name in dirname.split("/"):
            dir_path = f"{dir_path}/{dir_name}"
            target[dir_path[2:]] = None

    for file_rel in all_rel_files:
        if "__pycache__" in file_rel.split("/"):
            continue
        dirname, _, filename = file_rel.rpartition("/")
        if filename == "__init__.py":
            ignored[dirname] = None
            dirname, _, _ = dirname.rpartition("/")
        elif filename.endswith((".py", ".pyd", ".so")):
            pass
        else:
            continue

        if dirname in dirs or not dirname:
            continue
        add_all(dirname, dirs)

    for d in sorted(d for d in dirs if d not in ignored):
        init_path = site_packages_dir / d / "__init__.py"
        if not init_path.exists():
            init_path.write_text(init_content, encoding="utf-8")


def single_wheel_in(wheel_dir: Path, *, check_stray: bool = False) -> Path:
    """Return the single `.whl` file inside `wheel_dir`, or raise `ValueError`."""
    entries = sorted(wheel_dir.iterdir())
    whls = [p for p in entries if p.is_file() and p.suffix == ".whl"]
    if len(whls) != 1:
        raise ValueError(
            f"Expected 1 .whl file in '{wheel_dir}', found {len(whls)}: {[p.name for p in whls]}"
        )
    if check_stray and len(entries) != 1:
        stray = [p.name for p in entries if p != whls[0]]
        raise ValueError(f"Unexpected non-wheel files in '{wheel_dir}': {stray}")
    return whls[0]


_HUNK_HEADER_RE = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_UNSUPPORTED_PATCH_PREFIXES = (
    b"Binary files ",
    b"GIT binary patch",
    b"rename from ",
    b"rename to ",
    b"copy from ",
    b"copy to ",
)


def _strip_patch_path(raw_path: bytes, strip: int) -> str:
    path_bytes = raw_path.split(b"\t", 1)[0].strip()
    try:
        path = path_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Non-UTF-8 path in patch header: {raw_path!r}") from exc
    if path == "/dev/null":
        return path
    if path.startswith("/") or "\\" in path or ":" in path.split("/", 1)[0]:
        raise ValueError(f"Unsafe patch path: {path!r}")
    parts = [p for p in path.split("/") if p]
    if strip >= len(parts):
        raise ValueError(f"Cannot strip {strip} components from patch path '{path}'")
    return "/".join(parts[strip:])


def _find_hunk_position(
    file_lines: list[bytes],
    preferred_pos: int,
    old_ops: list[bytes],
    min_pos: int = 0,
) -> int | None:
    def _matches(pos: int) -> bool:
        return (
            min_pos <= pos
            and pos + len(old_ops) <= len(file_lines)
            and all(
                file_lines[pos + idx].rstrip(b"\r\n") == expected
                for idx, expected in enumerate(old_ops)
            )
        )

    if not old_ops:
        return preferred_pos if min_pos <= preferred_pos <= len(file_lines) else None
    if _matches(preferred_pos):
        return preferred_pos
    max_delta = max(preferred_pos - min_pos, len(file_lines) - preferred_pos)
    for delta in range(1, max_delta + 1):
        for candidate in (preferred_pos - delta, preferred_pos + delta):
            if _matches(candidate):
                return candidate
    return None


def apply_unified_patch(
    root_dir: Path,
    patch_path: Path,
    strip: int = 0,
) -> set[str]:
    """Apply a unified diff file strictly under `root_dir`, preserving line endings.

    Returns the set of relative POSIX paths under `root_dir` touched by the patch.
    """
    root_resolved = root_dir.resolve()
    lines = patch_path.read_bytes().splitlines(keepends=True)
    i = 0
    n = len(lines)
    applied_any = False
    just_finished_hunk = False
    touched: set[str] = set()

    while i < n:
        line = lines[i]
        if line.startswith(_UNSUPPORTED_PATCH_PREFIXES):
            raise ValueError(
                f"Unsupported binary or rename/copy patch directive in {patch_path}: {line!r}"
            )
        is_file_header = (
            line.startswith(b"--- ") and i + 1 < n and lines[i + 1].startswith(b"+++ ")
        )
        if not is_file_header:
            if _HUNK_HEADER_RE.match(line):
                raise ValueError(
                    f"Hunk without preceding '--- '/'+++ ' file header in {patch_path}: {line!r}"
                )
            if (
                just_finished_hunk
                and line.startswith((b"+", b"-", b" "))
                and not line.startswith(b"+++ ")
                and line not in (b"-- \n", b"-- \r\n")
            ):
                raise ValueError(
                    f"Unexpected diff body line outside hunk in {patch_path}: {line!r}"
                )
            just_finished_hunk = False
            i += 1
            continue
        just_finished_hunk = False

        old_rel = _strip_patch_path(line[4:], strip)
        new_rel = _strip_patch_path(lines[i + 1][4:], strip)
        i += 2

        if (
            strip == 0
            and (old_rel.startswith("a/") or old_rel == "/dev/null")
            and (new_rel.startswith("b/") or new_rel == "/dev/null")
            and (old_rel != "/dev/null" or new_rel != "/dev/null")
        ):
            raise ValueError(
                f"Patch {patch_path}: patch looks git-formatted (a/ b/ prefixes); use strip=1"
            )

        target_rel = old_rel if new_rel == "/dev/null" else new_rel
        target_file = root_dir / target_rel
        target_resolved = target_file.resolve()
        if (
            not target_resolved.is_relative_to(root_resolved)
            or target_resolved == root_resolved
        ):
            raise ValueError(
                f"Patch target '{target_rel}' escapes root directory '{root_dir}'"
            )

        if old_rel == "/dev/null":
            if target_file.exists():
                raise ValueError(
                    f"Patch {patch_path} attempts to create existing file '{target_rel}'"
                )
            file_lines: list[bytes] = []
        elif not target_file.exists():
            raise ValueError(
                f"Patch {patch_path} targets non-existent file '{target_rel}'"
            )
        else:
            file_lines = target_file.read_bytes().splitlines(keepends=True)

        eol = b"\r\n" if any(fl.endswith(b"\r\n") for fl in file_lines) else b"\n"

        offset = 0
        min_pos = 0
        file_had_hunk = False
        while i < n and lines[i].startswith(b"@@ "):
            m = _HUNK_HEADER_RE.match(lines[i])
            if not m:
                raise ValueError(f"Invalid hunk header in {patch_path}: {lines[i]!r}")
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) is not None else 1
            new_count = int(m.group(3)) if m.group(3) is not None else 1
            i += 1

            rem_old = old_count
            rem_new = new_count
            hunk_ops: list[tuple[bytes, bytes, bool]] = []

            while rem_old > 0 or rem_new > 0:
                if i >= n:
                    raise ValueError(
                        f"Unexpected end of patch {patch_path} inside hunk for {target_rel}"
                    )
                hline = lines[i]
                i += 1
                if hline in (b"\n", b"\r\n") and rem_old > 0 and rem_new > 0:
                    op = b" "
                    body = b""
                else:
                    op = hline[:1]
                    body = hline[1:].rstrip(b"\r\n")
                if op == b" ":
                    if rem_old <= 0 or rem_new <= 0:
                        raise ValueError(
                            f"Unexpected context line in {patch_path} for {target_rel}"
                        )
                    rem_old -= 1
                    rem_new -= 1
                elif op == b"-":
                    if rem_old <= 0:
                        raise ValueError(
                            f"Unexpected deletion line in {patch_path} for {target_rel}"
                        )
                    rem_old -= 1
                elif op == b"+":
                    if rem_new <= 0:
                        raise ValueError(
                            f"Unexpected addition line in {patch_path} for {target_rel}"
                        )
                    rem_new -= 1
                else:
                    raise ValueError(
                        f"Malformed hunk line in {patch_path} for {target_rel}: {hline!r}"
                    )

                no_nl = False
                if i < n and lines[i].startswith(b"\\"):
                    no_nl = True
                    i += 1
                hunk_ops.append((op, body, no_nl))

            old_bodies = [body for op, body, _ in hunk_ops if op in (b" ", b"-")]
            if old_count == 0:
                preferred = max(0, old_start + offset)
            else:
                preferred = 0 if old_start == 0 else max(0, old_start - 1 + offset)
            match_pos = _find_hunk_position(
                file_lines, preferred, old_bodies, min_pos=min_pos
            )
            if match_pos is None:
                raise ValueError(
                    f"Patch {patch_path} failed to apply to {target_rel} at line {old_start}: context mismatch"
                )

            replacement: list[bytes] = []
            cur_old = match_pos
            for op, body, no_nl in hunk_ops:
                if op == b" ":
                    orig_line = file_lines[cur_old]
                    cur_old += 1
                    if no_nl:
                        replacement.append(orig_line.rstrip(b"\r\n"))
                    elif not orig_line.endswith((b"\n", b"\r\n")):
                        replacement.append(orig_line + eol)
                    else:
                        replacement.append(orig_line)
                elif op == b"-":
                    cur_old += 1
                elif op == b"+":
                    replacement.append(body if no_nl else (body + eol))

            file_lines[match_pos:cur_old] = replacement
            offset += len(replacement) - (cur_old - match_pos)
            min_pos = match_pos + len(replacement)
            file_had_hunk = True
            applied_any = True

        just_finished_hunk = True
        if not file_had_hunk:
            raise ValueError(
                f"Patch {patch_path} has file header for {target_rel} without any hunks"
            )

        if new_rel == "/dev/null":
            if file_lines:
                raise ValueError(
                    f"Delete patch {patch_path} for '{target_rel}' did not consume entire file"
                )
            if target_file.exists():
                target_file.unlink()
        else:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_bytes(b"".join(file_lines))
        touched.add(target_rel)

    if not applied_any:
        raise ValueError(f"No valid unified diff hunks found in {patch_path}")

    return touched


def _record_row(entry_path: str, full_path: Path) -> list[str]:
    if entry_path.endswith((".pyc", ".pyo")):
        return [entry_path, "", ""]
    data = full_path.read_bytes()
    digest = (
        base64.urlsafe_b64encode(hashlib.sha256(data).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return [entry_path, f"sha256={digest}", str(len(data))]


def update_record_for_touched_files(
    site_packages_dir: Path,
    dist_info_dir: str,
    touched_site_rel_paths: set[str],
) -> None:
    """Update RECORD in `site-packages/<dist_info_dir>/RECORD` for touched files."""
    record_path = site_packages_dir / dist_info_dir / "RECORD"
    if not record_path.is_file():
        return

    existing_text = record_path.read_text(encoding="utf-8")
    out_buf = io.StringIO()
    writer = csv.writer(out_buf, lineterminator="\n")
    seen_touched: set[str] = set()

    for row in csv.reader(io.StringIO(existing_text)):
        if not row:
            continue
        entry_path = row[0]
        if entry_path in touched_site_rel_paths:
            seen_touched.add(entry_path)
            full_path = site_packages_dir / entry_path
            if full_path.is_file():
                writer.writerow(_record_row(entry_path, full_path))
        else:
            writer.writerow(row)

    for entry_path in sorted(touched_site_rel_paths - seen_touched):
        full_path = site_packages_dir / entry_path
        if full_path.is_file():
            writer.writerow(_record_row(entry_path, full_path))

    record_path.write_text(out_buf.getvalue(), encoding="utf-8")

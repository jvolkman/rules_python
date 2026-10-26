"""Rewrites a wheel's RECORD file to reflect its final installed layout."""

import sys


def rewrite_record_lines(lines, target_os, data_dir_basename, rewritten_scripts):
    data_prefix = data_dir_basename + "/"
    quoted_data_prefix = '"' + data_prefix

    if target_os == "windows":
        data_repl = "../../"
        headers_repl = "../../Include/"
        platlib_repl = ""
        purelib_repl = ""
        scripts_repl = "../../Scripts/"
    else:
        data_repl = "../../../"
        headers_repl = "../../../include/"
        platlib_repl = ""
        purelib_repl = ""
        scripts_repl = "../../../bin/"

    out_lines = []
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")

        if line.startswith(quoted_data_prefix):
            quote = '"'
            rest = line[len(quoted_data_prefix) :]
        elif line.startswith(data_prefix):
            quote = ""
            rest = line[len(data_prefix) :]
        else:
            out_lines.append(line + "\n")
            continue

        if rest.startswith("purelib/"):
            out_lines.append(quote + purelib_repl + rest[len("purelib/") :] + "\n")
        elif rest.startswith("platlib/"):
            out_lines.append(quote + platlib_repl + rest[len("platlib/") :] + "\n")
        elif rest.startswith("scripts/"):
            entry = rest[len("scripts/") :]
            if target_os == "windows":
                sep = '"' if quote == '"' else ","
                idx = entry.find(sep)
                if idx == -1:
                    out_lines.append(line + "\n")
                    continue
                spath, suffix = entry[:idx], entry[idx:]
                if spath in rewritten_scripts:
                    spath += ".bat"
                out_lines.append(quote + scripts_repl + spath + suffix + "\n")
            else:
                out_lines.append(quote + scripts_repl + entry + "\n")
        elif rest.startswith("headers/"):
            out_lines.append(quote + headers_repl + rest[len("headers/") :] + "\n")
        elif rest.startswith("data/"):
            out_lines.append(quote + data_repl + rest[len("data/") :] + "\n")
        else:
            out_lines.append(line + "\n")
    return out_lines


def rewrite_record_file(
    in_path, out_path, target_os, data_dir_basename, rewritten_scripts
):
    # PEP 427 specifies archive filenames are UTF-8, and while the encoding of
    # dist-info files isn't formally standardized in PEP 376, packaging tools
    # like pip and importlib.metadata treat them as UTF-8 in practice.
    # See: https://discuss.python.org/t/encoding-of-files-in-the-dist-info-directory/6734/4
    with open(in_path, encoding="utf-8") as in_file:
        out_lines = rewrite_record_lines(
            in_file, target_os, data_dir_basename, rewritten_scripts
        )
    with open(out_path, "w", encoding="utf-8", newline="\n") as out_file:
        out_file.writelines(out_lines)


def main(argv):
    in_path, out_path, target_os, data_dir_basename = argv[1:5]
    rewritten_scripts = set(argv[5:])
    rewrite_record_file(
        in_path, out_path, target_os, data_dir_basename, rewritten_scripts
    )


if __name__ == "__main__":
    main(sys.argv)

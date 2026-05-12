#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
import os
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional


class Color:
    ENABLED = True

    @staticmethod
    def _wrap(code: str, text: str) -> str:
        if not Color.ENABLED or not sys.stderr.isatty():
            return text
        return f"\033[{code}m{text}\033[0m"

    @staticmethod
    def red(text: str) -> str:     return Color._wrap("31", text)
    @staticmethod
    def green(text: str) -> str:   return Color._wrap("32", text)
    @staticmethod
    def yellow(text: str) -> str:  return Color._wrap("33", text)
    @staticmethod
    def blue(text: str) -> str:    return Color._wrap("34", text)
    @staticmethod
    def magenta(text: str) -> str: return Color._wrap("35", text)
    @staticmethod
    def cyan(text: str) -> str:    return Color._wrap("36", text)
    @staticmethod
    def bold(text: str) -> str:    return Color._wrap("1", text)
    @staticmethod
    def dim(text: str) -> str:     return Color._wrap("2", text)


class LintLevel(Enum):
    ERROR = "error"
    WARN = "warning"
    INFO = "info"


@dataclass
class LintIssue:
    level: LintLevel
    code: str
    message: str
    field_path: str = ""
    suggestion: str = ""


V_KEYWORDS = frozenset({
    "break", "const", "continue", "defer", "else", "enum", "fn",
    "for", "go", "goto", "if", "import", "in", "interface", "match",
    "module", "mut", "none", "pub", "return", "struct", "type",
    "typeof", "union", "unsafe", "as", "asm", "assert", "atomic",
    "shared", "lock", "rlock", "spawn", "sql", "is", "or",
    "true", "false", "__global", "__offsetof",
})

V_BUILTIN_TYPES = frozenset({
    "bool", "string", "int", "i8", "i16", "int", "i64",
    "u8", "u16", "u32", "u64", "f32", "f64",
    "byte", "rune", "voidptr", "byteptr", "charptr",
    "any", "any_int", "any_float",
})


def is_snake_case(name: str) -> bool:
    if not name:
        return False
    if name.startswith("_") or name.endswith("_"):
        return False
    if "__" in name:
        return False
    return bool(re.fullmatch(r"[a-z][a-z0-9_]*", name))


def camel_to_snake(name: str) -> str:
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return s2.lower()


def is_valid_v_field_name(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z_][a-z0-9_]*", name))


def infer_list_type(items: list, key: str, path: str, issues: list[LintIssue]) -> str:
    if not items:
        issues.append(LintIssue(
            level=LintLevel.WARN,
            code="V001",
            message=f"List '{path}' is empty, cannot infer element type, defaulting to []any",
            field_path=path,
            suggestion="Manually specify the element type",
        ))
        return "[]any"

    element_types: list[str] = []
    for item in items:
        if item is None:
            element_types.append("?any")
        elif isinstance(item, bool):
            element_types.append("bool")
        elif isinstance(item, int):
            element_types.append("int")
        elif isinstance(item, float):
            element_types.append("f64")
        elif isinstance(item, str):
            element_types.append("string")
        elif isinstance(item, list):
            element_types.append("[]any")
        elif isinstance(item, dict):
            element_types.append("struct")

    unique_types = list(dict.fromkeys(element_types))

    if len(unique_types) == 1:
        t = unique_types[0]
        if t == "struct":
            merged: dict[str, Any] = {}
            for item in items:
                if isinstance(item, dict):
                    for k, v in item.items():
                        if k not in merged:
                            merged[k] = v
            return f"[]{key.capitalize()}"
        return f"[]{t}"
    elif len(unique_types) == 2 and "?any" in unique_types:
        real_type = [t for t in unique_types if t != "?any"][0]
        return f"[]?{real_type.lstrip('?')}"
    else:
        issues.append(LintIssue(
            level=LintLevel.WARN,
            code="V002",
            message=f"List '{path}' contains mixed element types {unique_types}, using []any",
            field_path=path,
            suggestion="Manually specify the element type or ensure JSON data consistency",
        ))
        return "[]any"


def python_type_to_v(
    val: Any,
    key: str,
    path: str,
    issues: list[LintIssue],
    indent: int = 4,
    fix: bool = False,
    nested_structs: list[str] | None = None,
) -> str:
    prefix = " " * indent

    if val is None:
        issues.append(LintIssue(
            level=LintLevel.WARN,
            code="V003",
            message=f"Field '{path}' has null value, unable to determine concrete type",
            field_path=path,
            suggestion="Manually replace '?any' with a concrete optional type, e.g. '?string'",
        ))
        return f"{prefix}[json: {key}]\n{prefix}mut {key} ?any"

    if isinstance(val, bool):
        return f"{prefix}[json: {key}]\n{prefix}mut {key} bool"

    if isinstance(val, int):
        return f"{prefix}[json: {key}]\n{prefix}mut {key} int"

    if isinstance(val, float):
        return f"{prefix}[json: {key}]\n{prefix}mut {key} f64"

    if isinstance(val, str):
        return f"{prefix}[json: {key}]\n{prefix}mut {key} string"

    if isinstance(val, list):
        list_type = infer_list_type(val, key, path, issues)
        if val and isinstance(val[0], dict) and nested_structs is not None:
            merged: dict[str, Any] = {}
            for item in val:
                if isinstance(item, dict):
                    for k, v in item.items():
                        if k not in merged:
                            merged[k] = v
            struct_name = key.capitalize()
            struct_lines = f"pub struct {struct_name} {{\n"
            for k, v in merged.items():
                struct_lines += python_type_to_v(
                    v, k, f"{path}.{k}", issues, indent=4, fix=fix,
                    nested_structs=nested_structs,
                ) + "\n"
            struct_lines += "}\n"
            nested_structs.append(struct_lines)
        return f"{prefix}[json: {key}]\n{prefix}mut {key} {list_type}"

    if isinstance(val, dict):
        lines = f"{prefix}[json: {key}]\n{prefix}mut {key} struct {{\n"
        for k, v in val.items():
            lines += python_type_to_v(
                v, k, f"{path}.{k}", issues, indent + 4, fix=fix,
                nested_structs=nested_structs,
            ) + "\n"
        lines += f"{prefix}}}"
        return lines

    issues.append(LintIssue(
        level=LintLevel.ERROR,
        code="V004",
        message=f"Field '{path}' value type {type(val).__name__} cannot be mapped to a V type",
        field_path=path,
        suggestion="Manually specify the V type for this field",
    ))
    return f"{prefix}[json: {key}]\n{prefix}mut {key} any"


def lint_field_name(
    key: str,
    path: str,
    issues: list[LintIssue],
    fix: bool = False,
) -> str:
    if key in V_KEYWORDS:
        if fix:
            new_key = f"{key}_"
            issues.append(LintIssue(
                level=LintLevel.WARN,
                code="V010",
                message=f"Field '{path}' is a V reserved word, automatically appended underscore -> '{new_key}'",
                field_path=path,
                suggestion=f"auto-fix: {key} -> {new_key}",
            ))
            return new_key
        else:
            issues.append(LintIssue(
                level=LintLevel.ERROR,
                code="V010",
                message=f"Field '{path}' is a V reserved word '{key}', will cause compilation error",
                field_path=path,
                suggestion=f"Use --fix to automatically append underscore, or rename manually to '{key}_'",
            ))

    if key in V_BUILTIN_TYPES:
        if fix:
            new_key = f"{key}_val"
            issues.append(LintIssue(
                level=LintLevel.WARN,
                code="V011",
                message=f"Field '{path}' conflicts with built-in type, automatically renamed -> '{new_key}'",
                field_path=path,
                suggestion=f"auto-fix: {key} -> {new_key}",
            ))
            return new_key
        else:
            issues.append(LintIssue(
                level=LintLevel.ERROR,
                code="V011",
                message=f"Field '{path}' conflicts with V built-in type '{key}'",
                field_path=path,
                suggestion=f"Use --fix to auto-rename, or manually change to '{key}_val'",
            ))

    if not is_snake_case(key):
        if is_valid_v_field_name(key) and not any(c.isupper() for c in key):
            pass
        else:
            snake = camel_to_snake(key)
            if fix and snake != key:
                issues.append(LintIssue(
                    level=LintLevel.WARN,
                    code="V012",
                    message=f"Field '{path}' is not snake_case, automatically converted -> '{snake}'",
                    field_path=path,
                    suggestion=f"auto-fix: {key} -> {snake}",
                ))
                return snake
            else:
                issues.append(LintIssue(
                    level=LintLevel.WARN,
                    code="V012",
                    message=f"Field '{path}' does not follow V snake_case naming convention",
                    field_path=path,
                    suggestion=f"Use --fix to auto-convert to '{snake}', or rename manually",
                ))

    if key and key[0].isdigit():
        new_key = f"field_{key}"
        if fix:
            issues.append(LintIssue(
                level=LintLevel.WARN,
                code="V013",
                message=f"Field '{path}' starts with a digit, automatically prefixed -> '{new_key}'",
                field_path=path,
                suggestion=f"auto-fix: {key} -> {new_key}",
            ))
            return new_key
        else:
            issues.append(LintIssue(
                level=LintLevel.ERROR,
                code="V013",
                message=f"Field '{path}' starts with a digit, which is not allowed in V",
                field_path=path,
                suggestion=f"Use --fix to automatically add 'field_' prefix, or rename manually",
            ))

    return key


def lint_duplicate_fields(
    data: dict,
    path: str,
    issues: list[LintIssue],
) -> None:
    pass


def lint_root_not_object(data: Any, issues: list[LintIssue]) -> bool:
    if not isinstance(data, dict):
        issues.append(LintIssue(
            level=LintLevel.ERROR,
            code="V020",
            message=f"JSON root must be an object (dict), got {type(data).__name__}",
            field_path="<root>",
            suggestion="V structs can only be generated from JSON objects; ensure input is {...} format",
        ))
        return False
    return True


def json_to_v(
    key: str,
    val: Any,
    indent: int = 4,
    issues: list[LintIssue] | None = None,
    fix: bool = False,
    path: str = "",
    nested_structs: list[str] | None = None,
) -> str:
    if issues is None:
        issues = []

    current_path = f"{path}.{key}" if path else key

    resolved_key = lint_field_name(key, current_path, issues, fix=fix)

    prefix = " " * indent

    if val is None:
        issues.append(LintIssue(
            level=LintLevel.WARN,
            code="V003",
            message=f"Field '{current_path}' has null value, unable to determine concrete type",
            field_path=current_path,
            suggestion="Manually replace '?any' with a concrete optional type, e.g. '?string'",
        ))
        return f"{prefix}[json: {key}]\n{prefix}mut {resolved_key} ?any"

    if isinstance(val, bool):
        return f"{prefix}[json: {key}]\n{prefix}mut {resolved_key} bool"

    if isinstance(val, int):
        return f"{prefix}[json: {key}]\n{prefix}mut {resolved_key} int"

    if isinstance(val, float):
        return f"{prefix}[json: {key}]\n{prefix}mut {resolved_key} f64"

    if isinstance(val, str):
        return f"{prefix}[json: {key}]\n{prefix}mut {resolved_key} string"

    if isinstance(val, list):
        list_type = infer_list_type(val, resolved_key, current_path, issues)
        if val and isinstance(val[0], dict) and nested_structs is not None:
            merged: dict[str, Any] = {}
            for item in val:
                if isinstance(item, dict):
                    for k, v in item.items():
                        if k not in merged:
                            merged[k] = v
            struct_name = resolved_key.capitalize()
            struct_lines = f"pub struct {struct_name} {{\n"
            for k, v in merged.items():
                struct_lines += json_to_v(
                    k, v, indent=4, issues=issues, fix=fix,
                    path=struct_name, nested_structs=nested_structs,
                ) + "\n"
            struct_lines += "}\n"
            nested_structs.append(struct_lines)
        return f"{prefix}[json: {key}]\n{prefix}mut {resolved_key} {list_type}"

    if isinstance(val, dict):
        lines = f"{prefix}[json: {key}]\n{prefix}mut {resolved_key} struct {{\n"
        for k, v in val.items():
            lines += json_to_v(
                k, v, indent + 4, issues=issues, fix=fix,
                path=current_path, nested_structs=nested_structs,
            ) + "\n"
        lines += f"{prefix}}}"
        return lines

    issues.append(LintIssue(
        level=LintLevel.ERROR,
        code="V004",
        message=f"Field '{current_path}' value type {type(val).__name__} cannot be mapped to a V type",
        field_path=current_path,
        suggestion="Manually specify the V type for this field",
    ))
    return f"{prefix}[json: {key}]\n{prefix}mut {resolved_key} any"


def generate_v_struct(
    data: dict,
    root_name: str = "Root",
    fix: bool = False,
    lint_enabled: bool = False,
) -> tuple[str, list[LintIssue]]:
    issues: list[LintIssue] = []
    nested_structs: list[str] = []

    lines = "import json\n\n"
    lines += f"pub struct {root_name} {{\n"

    for k, v in data.items():
        lines += json_to_v(
            k, v, indent=4, issues=issues, fix=fix,
            path=root_name, nested_structs=nested_structs,
        ) + "\n"

    lines += "}\n"

    for ns in nested_structs:
        lines += f"\n{ns}\n"

    if fix:
        _check_post_fix_duplicates(data, root_name, issues)

    return lines, issues


def _check_post_fix_duplicates(data: dict, root_name: str, issues: list[LintIssue]) -> None:
    seen: dict[str, str] = {}
    for key in data.keys():
        fixed = lint_field_name(key, f"{root_name}.{key}", [], fix=True)
        if fixed in seen:
            issues.append(LintIssue(
                level=LintLevel.ERROR,
                code="V014",
                message=f"Post-fix name collision: '{seen[fixed]}' and '{key}' both renamed to '{fixed}'",
                field_path=f"{root_name}.{fixed}",
                suggestion="Resolve the naming conflict manually",
            ))
        else:
            seen[fixed] = key


def format_lint_report(issues: list[LintIssue], verbose: bool = False) -> str:
    if not issues:
        return Color.green("✓ No lint issues found; generated code looks good!")

    errors = [i for i in issues if i.level == LintLevel.ERROR]
    warnings = [i for i in issues if i.level == LintLevel.WARN]
    infos = [i for i in issues if i.level == LintLevel.INFO]

    lines = []
    lines.append("")
    lines.append(Color.bold("═" * 60))
    lines.append(Color.bold("  Lint Diagnostic Report"))
    lines.append(Color.bold("═" * 60))

    if errors:
        lines.append("")
        lines.append(Color.red(Color.bold(f"  ✗ Errors ({len(errors)})")))
        for issue in errors:
            lines.append(f"    {Color.red('[' + issue.code + ']')} {issue.message}")
            if issue.field_path:
                lines.append(f"      {Color.dim('Location: ' + issue.field_path)}")
            if issue.suggestion and verbose:
                lines.append(f"      {Color.cyan('Suggestion: ' + issue.suggestion)}")

    if warnings:
        lines.append("")
        lines.append(Color.yellow(Color.bold(f"  ⚠ Warnings ({len(warnings)})")))
        for issue in warnings:
            lines.append(f"    {Color.yellow('[' + issue.code + ']')} {issue.message}")
            if issue.field_path:
                lines.append(f"      {Color.dim('Location: ' + issue.field_path)}")
            if issue.suggestion:
                lines.append(f"      {Color.cyan('Suggestion: ' + issue.suggestion)}")

    if infos and verbose:
        lines.append("")
        lines.append(Color.blue(Color.bold(f"  ℹ Info ({len(infos)})")))
        for issue in infos:
            lines.append(f"    {Color.blue('[' + issue.code + ']')} {issue.message}")

    lines.append("")
    summary_parts = []
    if errors:
        summary_parts.append(Color.red(f"{len(errors)} error(s)"))
    if warnings:
        summary_parts.append(Color.yellow(f"{len(warnings)} warning(s)"))
    if infos:
        summary_parts.append(Color.blue(f"{len(infos)} info(s)"))

    lines.append(f"  Total: {', '.join(summary_parts)}")
    lines.append(Color.bold("═" * 60))
    lines.append("")

    return "\n".join(lines)


def read_input(input_path: str | None) -> str:
    try:
        if input_path is None:
            if sys.stdin.isatty():
                print(Color.yellow("Waiting for JSON input from stdin... (Ctrl+D to end)"), file=sys.stderr)
            raw = sys.stdin.read()
        else:
            if not os.path.exists(input_path):
                raise FileNotFoundError(f"Input file not found: {input_path}")
            with open(input_path, "r", encoding="utf-8") as f:
                raw = f.read()
    except FileNotFoundError as e:
        print(Color.red(f"✗ File error: {e}"), file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print(Color.red(f"✗ Permission error: cannot read file '{input_path}'"), file=sys.stderr)
        sys.exit(1)
    except UnicodeDecodeError:
        print(Color.red(f"✗ Encoding error: file '{input_path}' is not valid UTF-8"), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print(Color.yellow("\nInput cancelled"), file=sys.stderr)
        sys.exit(130)

    if not raw.strip():
        print(Color.red("✗ Input is empty, please provide valid JSON"), file=sys.stderr)
        print(Color.dim("  Hint: pipe JSON via stdin, e.g. echo '{\"key\":\"value\"}' | python3 json2v.py"), file=sys.stderr)
        print(Color.dim("  Or use the -i option to specify a file, e.g. python3 json2v.py -i data.json"), file=sys.stderr)
        sys.exit(1)

    return raw


def parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(Color.red(f"✗ JSON parse error: {e}"), file=sys.stderr)
        print(Color.dim(f"  Location: line {e.lineno}, column {e.colno}"), file=sys.stderr)

        lines = raw.split("\n")
        if 0 < e.lineno <= len(lines):
            error_line = lines[e.lineno - 1]
            print(Color.dim(f"  Content: {error_line}"), file=sys.stderr)
            if e.colno > 0:
                pointer = " " * (len("  Content: ") + e.colno - 1) + "^"
                print(Color.red(pointer), file=sys.stderr)

        print(Color.dim("  Hint: check for unmatched brackets, missing commas, or illegal characters"), file=sys.stderr)
        sys.exit(1)


def write_output(code: str, output_path: str | None) -> None:
    if output_path is None:
        print(code)
    else:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(code)
            print(Color.green(f"✓ Written to: {output_path}"), file=sys.stderr)
        except PermissionError:
            print(Color.red(f"✗ Permission error: cannot write file '{output_path}'"), file=sys.stderr)
            sys.exit(1)
        except OSError as e:
            print(Color.red(f"✗ Write error: {e}"), file=sys.stderr)
            sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="json2v",
        description="JSON -> V struct generator (enhanced)",
        epilog="""
Examples:
  echo '{"name":"Alice","age":30}' | %(prog)s           # read from stdin
  %(prog)s -i data.json                                  # read from file
  %(prog)s -i data.json -o output.v                      # output to file
  %(prog)s -i data.json --lint                           # enable lint checks
  %(prog)s -i data.json --lint --fix                     # lint + auto-fix
  %(prog)s -i data.json --lint --dry-run                 # check only, no output
  %(prog)s -i data.json --root Config                    # custom root struct name
  %(prog)s -i data.json -v                               # verbose output
  %(prog)s -i data.json --no-color                       # disable colored output

Lint codes:
  V001  Empty list, cannot infer element type
  V002  List contains mixed element types
  V003  Field value is null, cannot determine type
  V004  Value type cannot be mapped to V type
  V010  Field name is a V reserved word
  V011  Field name conflicts with V built-in type
  V012  Field name not in snake_case
  V013  Field name starts with a digit
  V014  Post-fix field name collision
  V020  JSON root is not an object
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    io_group = parser.add_argument_group("Input/Output")
    io_group.add_argument(
        "-i", "--input",
        metavar="FILE",
        help="Input JSON file path (default: read from stdin)",
    )
    io_group.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Output V file path (default: write to stdout)",
    )

    struct_group = parser.add_argument_group("Struct configuration")
    struct_group.add_argument(
        "--root",
        metavar="NAME",
        default="Root",
        help="Root struct name (default: Root)",
    )

    lint_group = parser.add_argument_group("Lint and fix")
    lint_group.add_argument(
        "--lint",
        action="store_true",
        help="Enable lint checks for naming, reserved words, type inference, etc.",
    )
    lint_group.add_argument(
        "--fix",
        action="store_true",
        help="Auto-fix lint issues (camelCase->snake_case, reserved word escaping, etc.)",
    )
    lint_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Run lint checks only, do not output generated code",
    )

    output_group = parser.add_argument_group("Output control")
    output_group.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output with more diagnostic details",
    )
    output_group.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored terminal output",
    )
    output_group.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode: treat warnings as errors, exit code 1 on any warning",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="json2v 2.0.0 (enhanced)",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.no_color:
        Color.ENABLED = False

    if args.fix and not args.lint:
        args.lint = True

    if args.dry_run and not args.lint:
        args.lint = True

    if args.verbose:
        print(Color.dim("-> Reading input..."), file=sys.stderr)

    raw = read_input(args.input)

    if args.verbose:
        print(Color.dim("-> Parsing JSON..."), file=sys.stderr)

    data = parse_json(raw)

    issues: list[LintIssue] = []
    if not lint_root_not_object(data, issues):
        print(format_lint_report(issues, args.verbose), file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(Color.dim(f"-> Generating V struct (root: {args.root})..."), file=sys.stderr)

    code, gen_issues = generate_v_struct(
        data,
        root_name=args.root,
        fix=args.fix,
        lint_enabled=args.lint,
    )
    issues.extend(gen_issues)

    if args.lint and issues:
        print(format_lint_report(issues, args.verbose), file=sys.stderr)

    if args.strict:
        error_count = sum(1 for i in issues if i.level == LintLevel.ERROR)
        warn_count = sum(1 for i in issues if i.level == LintLevel.WARN)
        if error_count > 0 or warn_count > 0:
            if not args.dry_run:
                write_output(code, args.output)
            print(Color.red(f"✗ Strict mode: {error_count} error(s), {warn_count} warning(s)"), file=sys.stderr)
            sys.exit(1)

    if args.dry_run:
        if not issues:
            print(Color.green("✓ Dry-run passed, no lint issues found"), file=sys.stderr)
        else:
            error_count = sum(1 for i in issues if i.level == LintLevel.ERROR)
            if error_count > 0:
                sys.exit(1)
        return

    write_output(code, args.output)

    if args.lint:
        error_count = sum(1 for i in issues if i.level == LintLevel.ERROR)
        if error_count > 0:
            sys.exit(1)

    if args.verbose:
        print(Color.green("✓ Done"), file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re, sys, os
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional

class Color:
    ENABLED = True
    @staticmethod
    def _wrap(c: str, t: str) -> str:
        return t if not Color.ENABLED or not sys.stderr.isatty() else f"\033[{c}m{t}\033[0m"
    @staticmethod
    def red(t: str) -> str: return Color._wrap("31", t)
    @staticmethod
    def green(t: str) -> str: return Color._wrap("32", t)
    @staticmethod
    def yellow(t: str) -> str: return Color._wrap("33", t)
    @staticmethod
    def blue(t: str) -> str: return Color._wrap("34", t)
    @staticmethod
    def cyan(t: str) -> str: return Color._wrap("36", t)
    @staticmethod
    def bold(t: str) -> str: return Color._wrap("1", t)
    @staticmethod
    def dim(t: str) -> str: return Color._wrap("2", t)

class Level(Enum):
    ERROR = "error"
    WARN = "warning"
    INFO = "info"

@dataclass
class Issue:
    level: Level
    code: str
    message: str
    path: str = ""
    fix: str = ""

KWS = frozenset({"break","const","continue","defer","else","enum","fn","for","go","goto","if","import","in","interface","match","module","mut","none","pub","return","struct","type","typeof","union","unsafe","as","asm","assert","atomic","shared","lock","rlock","spawn","sql","is","or","true","false","__global","__offsetof"})
BUILTINS = frozenset({"bool","string","int","i8","i16","i64","u8","u16","u32","u64","f32","f64","byte","rune","voidptr","byteptr","charptr","any","any_int","any_float"})

def is_snake(s: str) -> bool:
    return bool(s and not s.startswith("_") and not s.endswith("_") and "__" not in s and re.fullmatch(r"[a-z][a-z0-9_]*", s))

def camel_to_snake(s: str) -> str:
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

@dataclass
class Ctx:
    issues: list[Issue]
    fix: bool
    nested: list[str]
    indent: int
    path: str
    def pfx(self) -> str: return " " * self.indent
    def sub(self, path: str, indent: int = None):
        return Ctx(self.issues, self.fix, self.nested, indent or self.indent + 4, path)

def infer_list(items: list, key: str, ctx: Ctx) -> str:
    if not items:
        ctx.issues.append(Issue(Level.WARN, "V001", f"Empty list '{ctx.path}', defaulting to []any", ctx.path, "Specify element type manually"))
        return "[]any"
    types = []
    for it in items:
        if it is None: types.append("?any")
        elif isinstance(it, bool): types.append("bool")
        elif isinstance(it, int): types.append("int")
        elif isinstance(it, float): types.append("f64")
        elif isinstance(it, str): types.append("string")
        elif isinstance(it, list): types.append("[]any")
        elif isinstance(it, dict): types.append("struct")
    uniq = list(dict.fromkeys(types))
    if len(uniq) == 1:
        t = uniq[0]
        return f"[]{key.capitalize()}" if t == "struct" else f"[]{t}"
    if len(uniq) == 2 and "?any" in uniq:
        real = [t for t in uniq if t != "?any"][0]
        return f"[]?{real.lstrip('?')}"
    ctx.issues.append(Issue(Level.WARN, "V002", f"Mixed types {uniq} in '{ctx.path}', using []any", ctx.path, "Ensure consistent element types"))
    return "[]any"

def lint_name(key: str, ctx: Ctx) -> str:
    orig = key
    if key in KWS:
        new = f"{key}_"
        ctx.issues.append(Issue(Level.WARN if ctx.fix else Level.ERROR, "V010", f"'{ctx.path}' is reserved word", ctx.path, f"auto-fix: {orig} -> {new}" if ctx.fix else f"Rename to '{new}'"))
        return new if ctx.fix else key
    if key in BUILTINS:
        new = f"{key}_val"
        ctx.issues.append(Issue(Level.WARN if ctx.fix else Level.ERROR, "V011", f"'{ctx.path}' conflicts with builtin type", ctx.path, f"auto-fix: {orig} -> {new}" if ctx.fix else f"Rename to '{new}'"))
        return new if ctx.fix else key
    if not is_snake(key):
        snake = camel_to_snake(key)
        if snake != key:
            ctx.issues.append(Issue(Level.WARN, "V012", f"'{ctx.path}' not snake_case", ctx.path, f"auto-fix: {orig} -> {snake}" if ctx.fix else f"Rename to '{snake}'"))
            return snake if ctx.fix else key
    if key and key[0].isdigit():
        new = f"field_{key}"
        ctx.issues.append(Issue(Level.WARN if ctx.fix else Level.ERROR, "V013", f"'{ctx.path}' starts with digit", ctx.path, f"auto-fix: {orig} -> {new}" if ctx.fix else f"Rename to '{new}'"))
        return new if ctx.fix else key
    return key

def convert(key: str, val: Any, ctx: Ctx) -> str:
    parts = []
    pfx = ctx.pfx()
    resolved = lint_name(key, ctx)
    path = f"{ctx.path}.{key}" if ctx.path else key
    parts.append(f"{pfx}[json: {key}]")
    if val is None:
        ctx.issues.append(Issue(Level.WARN, "V003", f"Null value at '{path}'", path, "Replace ?any with concrete optional type"))
        parts.append(f"{pfx}mut {resolved} ?any")
        return "\n".join(parts)
    if isinstance(val, bool):
        parts.append(f"{pfx}mut {resolved} bool")
        return "\n".join(parts)
    if isinstance(val, int):
        parts.append(f"{pfx}mut {resolved} int")
        return "\n".join(parts)
    if isinstance(val, float):
        parts.append(f"{pfx}mut {resolved} f64")
        return "\n".join(parts)
    if isinstance(val, str):
        parts.append(f"{pfx}mut {resolved} string")
        return "\n".join(parts)
    if isinstance(val, list):
        lt = infer_list(val, resolved, ctx)
        if val and isinstance(val[0], dict):
            merged = {}
            for it in val:
                if isinstance(it, dict):
                    for k, v in it.items():
                        if k not in merged: merged[k] = v
            sname = resolved.capitalize()
            sub_ctx = ctx.sub(sname, 4)
            struct_parts = [f"pub struct {sname} {{"]
            for k, v in merged.items():
                struct_parts.append(convert(k, v, sub_ctx.sub(f"{sname}.{k}")))
            struct_parts.append("}")
            ctx.nested.append("\n".join(struct_parts))
        parts.append(f"{pfx}mut {resolved} {lt}")
        return "\n".join(parts)
    if isinstance(val, dict):
        parts.append(f"{pfx}mut {resolved} struct {{")
        sub_ctx = ctx.sub(path)
        for k, v in val.items():
            parts.append(convert(k, v, sub_ctx.sub(f"{path}.{k}")))
        parts.append(f"{pfx}}}")
        return "\n".join(parts)
    ctx.issues.append(Issue(Level.ERROR, "V004", f"Unmappable type {type(val).__name__} at '{path}'", path, "Specify V type manually"))
    parts.append(f"{pfx}mut {resolved} any")
    return "\n".join(parts)

def gen_struct(data: dict, root: str, fix: bool) -> tuple[str, list[Issue]]:
    issues, nested = [], []
    ctx = Ctx(issues, fix, nested, 4, root)
    parts = ["import json\n", f"pub struct {root} {{"]
    for k, v in data.items():
        parts.append(convert(k, v, ctx.sub(f"{root}.{k}")))
    parts.append("}")
    for ns in nested:
        parts.append(f"\n{ns}\n")
    if fix:
        seen = {}
        for k in data:
            fixed = lint_name(k, Ctx([], True, [], 0, f"{root}.{k}"))
            if fixed in seen:
                issues.append(Issue(Level.ERROR, "V014", f"Name collision: '{seen[fixed]}' and '{k}' -> '{fixed}'", f"{root}.{fixed}", "Resolve manually"))
            seen[fixed] = k
    return "\n".join(parts), issues

def report(issues: list[Issue], verbose: bool) -> str:
    if not issues: return Color.green("✓ No lint issues")
    errs = [i for i in issues if i.level == Level.ERROR]
    warns = [i for i in issues if i.level == Level.WARN]
    lines = ["", Color.bold("═" * 60), Color.bold("  Lint Report"), Color.bold("═" * 60)]
    if errs:
        lines += ["", Color.red(Color.bold(f"  ✗ Errors ({len(errs)})"))]
        for i in errs:
            lines.append(f"    {Color.red('['+i.code+']')} {i.message}")
            if i.path: lines.append(f"      {Color.dim('Location: '+i.path)}")
            if i.fix and verbose: lines.append(f"      {Color.cyan('Fix: '+i.fix)}")
    if warns:
        lines += ["", Color.yellow(Color.bold(f"  ⚠ Warnings ({len(warns)})"))]
        for i in warns:
            lines.append(f"    {Color.yellow('['+i.code+']')} {i.message}")
            if i.path: lines.append(f"      {Color.dim('Location: '+i.path)}")
            if i.fix: lines.append(f"      {Color.cyan('Fix: '+i.fix)}")
    summary = []
    if errs: summary.append(Color.red(f"{len(errs)} error(s)"))
    if warns: summary.append(Color.yellow(f"{len(warns)} warning(s)"))
    lines += ["", f"  Total: {', '.join(summary)}", Color.bold("═" * 60), ""]
    return "\n".join(lines)

def read_in(path: str | None) -> str:
    try:
        if path is None:
            if sys.stdin.isatty(): print(Color.yellow("Waiting for stdin..."), file=sys.stderr)
            raw = sys.stdin.read()
        else:
            with open(path, "r", encoding="utf-8") as f: raw = f.read()
    except FileNotFoundError: print(Color.red(f"✗ File not found: {path}"), file=sys.stderr); sys.exit(1)
    except PermissionError: print(Color.red(f"✗ Permission denied: {path}"), file=sys.stderr); sys.exit(1)
    except UnicodeDecodeError: print(Color.red(f"✗ Encoding error: {path}"), file=sys.stderr); sys.exit(1)
    except KeyboardInterrupt: print(Color.yellow("\nCancelled"), file=sys.stderr); sys.exit(130)
    if not raw.strip(): print(Color.red("✗ Empty input"), file=sys.stderr); sys.exit(1)
    return raw

def parse_json(raw: str) -> Any:
    try: return json.loads(raw)
    except json.JSONDecodeError as e:
        print(Color.red(f"✗ JSON error: {e}"), file=sys.stderr)
        lines = raw.split("\n")
        if 0 < e.lineno <= len(lines):
            print(Color.dim(f"  Line {e.lineno}: {lines[e.lineno-1]}"), file=sys.stderr)
            if e.colno > 0: print(Color.red(" " * (e.colno + 2) + "^"), file=sys.stderr)
        sys.exit(1)

def write_out(code: str, path: str | None) -> None:
    if path is None: print(code)
    else:
        try:
            with open(path, "w", encoding="utf-8") as f: f.write(code)
            print(Color.green(f"✓ Written: {path}"), file=sys.stderr)
        except PermissionError: print(Color.red(f"✗ Cannot write: {path}"), file=sys.stderr); sys.exit(1)
        except OSError as e: print(Color.red(f"✗ Write error: {e}"), file=sys.stderr); sys.exit(1)

def mk_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="json2v", description="JSON → V struct generator", formatter_class=argparse.RawDescriptionHelpFormatter, epilog="""
Examples:
  echo '{"name":"Alice"}' | json2v
  json2v -i data.json -o out.v --lint --fix
  json2v -i data.json --root Config --strict

Lint codes: V001 empty list, V002 mixed types, V003 null value, V004 unmappable type
            V010 reserved word, V011 builtin conflict, V012 not snake_case
            V013 starts with digit, V014 name collision, V020 root not object
""")
    g = p.add_argument_group("I/O")
    g.add_argument("-i", "--input", metavar="FILE", help="Input JSON file")
    g.add_argument("-o", "--output", metavar="FILE", help="Output V file")
    g.add_argument("--root", default="Root", metavar="NAME", help="Root struct name")
    g.add_argument("--lint", action="store_true", help="Enable lint checks")
    g.add_argument("--fix", action="store_true", help="Auto-fix lint issues")
    g.add_argument("--dry-run", action="store_true", help="Lint only, no output")
    g.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    g.add_argument("--no-color", action="store_true", help="Disable colors")
    g.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    p.add_argument("--version", action="version", version="json2v 2.0")
    return p

def main() -> None:
    args = mk_parser().parse_args()
    if args.no_color: Color.ENABLED = False
    if args.fix and not args.lint: args.lint = True
    if args.dry_run and not args.lint: args.lint = True
    raw = read_in(args.input)
    data = parse_json(raw)
    issues = []
    if not isinstance(data, dict):
        issues.append(Issue(Level.ERROR, "V020", "JSON root must be object", "<root>", "Ensure input is {...}"))
        print(report(issues, args.verbose), file=sys.stderr)
        sys.exit(1)
    code, gen_issues = gen_struct(data, args.root, args.fix)
    issues.extend(gen_issues)
    if args.lint and issues: print(report(issues, args.verbose), file=sys.stderr)
    if args.strict:
        ec = sum(1 for i in issues if i.level == Level.ERROR)
        wc = sum(1 for i in issues if i.level == Level.WARN)
        if ec or wc:
            if not args.dry_run: write_out(code, args.output)
            print(Color.red(f"✗ Strict: {ec} error(s), {wc} warning(s)"), file=sys.stderr)
            sys.exit(1)
    if args.dry_run:
        if not issues: print(Color.green("✓ Dry-run passed"), file=sys.stderr)
        elif any(i.level == Level.ERROR for i in issues): sys.exit(1)
        return
    write_out(code, args.output)
    if args.lint and any(i.level == Level.ERROR for i in issues): sys.exit(1)

if __name__ == "__main__": main()

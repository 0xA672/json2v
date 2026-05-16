#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re, sys, os
from enum import Enum
from dataclasses import dataclass
from typing import Any

class Color:
    ENABLED = True
    @staticmethod
    def _w(c: str, t: str) -> str:
        return t if not Color.ENABLED or not sys.stderr.isatty() else f"\033[{c}m{t}\033[0m"
    @staticmethod
    def red(t: str) -> str: return Color._w("31", t)
    @staticmethod
    def green(t: str) -> str: return Color._w("32", t)
    @staticmethod
    def yellow(t: str) -> str: return Color._w("33", t)
    @staticmethod
    def blue(t: str) -> str: return Color._w("34", t)
    @staticmethod
    def cyan(t: str) -> str: return Color._w("36", t)
    @staticmethod
    def bold(t: str) -> str: return Color._w("1", t)
    @staticmethod
    def dim(t: str) -> str: return Color._w("2", t)

class Level(Enum):
    ERROR = "error"
    WARN = "warning"

@dataclass
class Issue:
    level: Level
    code: str
    msg: str
    path: str = ""
    fix: str = ""

KWS = frozenset({"break","const","continue","defer","else","enum","fn","for","go","goto","if","import","in","interface","match","module","mut","none","pub","return","struct","type","typeof","union","unsafe","as","asm","assert","atomic","shared","lock","rlock","spawn","sql","is","or","true","false","__global","__offsetof"})
BUILTINS = frozenset({"bool","string","int","i8","i16","i64","u8","u16","u32","u64","f32","f64","byte","rune","voidptr","byteptr","charptr","any","any_int","any_float"})
MAX_DEPTH = 100
MAX_SAMPLE = 50

def c2s(s: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)).lower()

def is_snake(s: str) -> bool:
    return bool(s and not s.startswith("_") and not s.endswith("_") and "__" not in s and re.fullmatch(r"[a-z][a-z0-9_]*", s))

@dataclass
class Ctx:
    issues: list[Issue]
    fix: bool
    nested: list[str]
    indent: int
    path: str
    depth: int
    def pfx(self) -> str: return " " * self.indent
    def sub(self, path: str, d: int = None):
        return Ctx(self.issues, self.fix, self.nested, self.indent + 4, path, d if d is not None else self.depth + 1)

def infer_list(items: list, key: str, ctx: Ctx) -> str:
    if not items:
        ctx.issues.append(Issue(Level.WARN, "V001", f"Empty list '{ctx.path}', defaulting to []any", ctx.path, "Specify element type manually"))
        return "[]any"
    sample = items[:MAX_SAMPLE]
    if len(items) > MAX_SAMPLE:
        ctx.issues.append(Issue(Level.INFO, "V005", f"List '{ctx.path}' truncated to {MAX_SAMPLE} for inference", ctx.path, ""))
    types = []
    field_types: dict[str, set[str]] = {}
    for it in sample:
        t = type(it).__name__
        if isinstance(it, dict):
            for k, v in it.items():
                if k not in field_types: field_types[k] = set()
                field_types[k].add(type(v).__name__)
        types.append(t)
    for k, ts in field_types.items():
        if len(ts) > 1:
            ctx.issues.append(Issue(Level.WARN, "V006", f"Field '{k}' in '{ctx.path}' has mixed types: {ts}", ctx.path, "Ensure consistent schema"))
    uniq = list(dict.fromkeys(types))
    if len(uniq) == 1:
        t = uniq[0]
        if t == "dict": return f"[]{key.capitalize()}"
        return f"[]{t}"
    if len(uniq) == 2 and "NoneType" in uniq:
        real = [t for t in uniq if t != "NoneType"][0]
        return f"[]?{real}"
    ctx.issues.append(Issue(Level.WARN, "V002", f"Mixed types {uniq} in '{ctx.path}', using []any", ctx.path, "Ensure consistent element types"))
    return "[]any"

def _py2v(t: str) -> str:
    m = {"bool":"bool","int":"int","float":"f64","str":"string","dict":"struct","list":"[]any","NoneType":"?any"}
    return m.get(t, "any")

def lint_name(key: str, ctx: Ctx) -> str:
    orig = key
    if key in KWS:
        new = f"{key}_"
        lv = Level.WARN if ctx.fix else Level.ERROR
        ctx.issues.append(Issue(lv, "V010", f"'{ctx.path}' is reserved word", ctx.path, f"auto-fix: {orig} -> {new}" if ctx.fix else f"Rename to '{new}'"))
        return new if ctx.fix else key
    if key in BUILTINS:
        new = f"{key}_val"
        lv = Level.WARN if ctx.fix else Level.ERROR
        ctx.issues.append(Issue(lv, "V011", f"'{ctx.path}' conflicts with builtin", ctx.path, f"auto-fix: {orig} -> {new}" if ctx.fix else f"Rename to '{new}'"))
        return new if ctx.fix else key
    if not is_snake(key):
        snake = c2s(key)
        if snake != key:
            ctx.issues.append(Issue(Level.WARN, "V012", f"'{ctx.path}' not snake_case", ctx.path, f"auto-fix: {orig} -> {snake}" if ctx.fix else f"Rename to '{snake}'"))
            return snake if ctx.fix else key
    if key and key[0].isdigit():
        new = f"f_{key}"
        lv = Level.WARN if ctx.fix else Level.ERROR
        ctx.issues.append(Issue(lv, "V013", f"'{ctx.path}' starts with digit", ctx.path, f"auto-fix: {orig} -> {new}" if ctx.fix else f"Rename to '{new}'"))
        return new if ctx.fix else key
    return key

def convert(key: str, val: Any, ctx: Ctx) -> str:
    if ctx.depth > MAX_DEPTH:
        ctx.issues.append(Issue(Level.ERROR, "V099", f"Max depth exceeded at '{ctx.path}'", ctx.path, "Flatten JSON structure"))
        return f"{ctx.pfx()}mut {key} any"
    pfx = ctx.pfx()
    resolved = lint_name(key, ctx)
    path = f"{ctx.path}.{key}" if ctx.path else key
    parts = [f"{pfx}[json: {key}]"]
    if val is None:
        ctx.issues.append(Issue(Level.WARN, "V003", f"Null value at '{path}'", path, "Replace ?any with concrete type"))
        parts.append(f"{pfx}mut {resolved} ?any")
        return "\n".join(parts)
    t = type(val).__name__
    if t == "bool":
        parts.append(f"{pfx}mut {resolved} bool")
    elif t == "int":
        parts.append(f"{pfx}mut {resolved} int")
    elif t == "float":
        parts.append(f"{pfx}mut {resolved} f64")
    elif t == "str":
        parts.append(f"{pfx}mut {resolved} string")
    elif t == "list":
        lt = infer_list(val, resolved, ctx)
        if val and isinstance(val[0], dict):
            merged: dict[str, Any] = {}
            for it in val:
                if isinstance(it, dict):
                    for k, v in it.items():
                        if k not in merged: merged[k] = v
            sname = resolved.capitalize()
            sub = ctx.sub(sname, 1)
            sp = [f"pub struct {sname} {{"]
            for k, v in merged.items():
                sp.append(convert(k, v, sub.sub(f"{sname}.{k}")))
            sp.append("}")
            ctx.nested.append("\n".join(sp))
        parts.append(f"{pfx}mut {resolved} {lt}")
    elif t == "dict":
        parts.append(f"{pfx}mut {resolved} struct {{")
        sub = ctx.sub(path, ctx.depth + 1)
        for k, v in val.items():
            parts.append(convert(k, v, sub.sub(f"{path}.{k}")))
        parts.append(f"{pfx}}}")
    else:
        ctx.issues.append(Issue(Level.ERROR, "V004", f"Unmappable type {t} at '{path}'", path, "Specify V type manually"))
        parts.append(f"{pfx}mut {resolved} any")
    return "\n".join(parts)

def gen(data: dict, root: str, fix: bool) -> tuple[str, list[Issue]]:
    issues, nested = [], []
    ctx = Ctx(issues, fix, nested, 4, root, 0)
    parts = ["import json\n", f"pub struct {root} {{"]
    for k, v in data.items():
        parts.append(convert(k, v, ctx.sub(f"{root}.{k}")))
    parts.append("}")
    for ns in nested:
        parts.append(f"\n{ns}\n")
    if fix:
        seen: dict[str, str] = {}
        for k in data:
            tmp_ctx = Ctx([], True, [], 0, f"{root}.{k}", 0)
            fixed = lint_name(k, tmp_ctx)
            if fixed in seen:
                issues.append(Issue(Level.ERROR, "V014", f"Collision: '{seen[fixed]}' and '{k}' -> '{fixed}'", f"{root}.{fixed}", "Resolve manually"))
            seen[fixed] = k
    return "\n".join(parts), issues

def rpt(issues: list[Issue], verbose: bool) -> str:
    if not issues: return Color.green("✓ No lint issues")
    errs = [i for i in issues if i.level == Level.ERROR]
    warns = [i for i in issues if i.level == Level.WARN]
    lines = ["", Color.bold("═" * 60), Color.bold("  Lint Report"), Color.bold("═" * 60)]
    if errs:
        lines += ["", Color.red(Color.bold(f"  ✗ Errors ({len(errs)})"))]
        for i in errs:
            lines.append(f"    {Color.red('['+i.code+']')} {i.msg}")
            if i.path: lines.append(f"      {Color.dim('Path: '+i.path)}")
            if i.fix and verbose: lines.append(f"      {Color.cyan('Fix: '+i.fix)}")
    if warns:
        lines += ["", Color.yellow(Color.bold(f"  ⚠ Warnings ({len(warns)})"))]
        for i in warns:
            lines.append(f"    {Color.yellow('['+i.code+']')} {i.msg}")
            if i.path: lines.append(f"      {Color.dim('Path: '+i.path)}")
            if i.fix: lines.append(f"      {Color.cyan('Fix: '+i.fix)}")
    s = []
    if errs: s.append(Color.red(f"{len(errs)} error(s)"))
    if warns: s.append(Color.yellow(f"{len(warns)} warning(s)"))
    lines += ["", f"  Total: {', '.join(s)}", Color.bold("═" * 60), ""]
    return "\n".join(lines)

def read_in(path: str | None) -> str:
    try:
        if path is None:
            if sys.stdin.isatty(): print(Color.yellow("Waiting for stdin..."), file=sys.stderr)
            return sys.stdin.read()
        with open(path, "r", encoding="utf-8", errors="replace") as f: return f.read()
    except FileNotFoundError: print(Color.red(f"✗ Not found: {path}"), file=sys.stderr); sys.exit(1)
    except PermissionError: print(Color.red(f"✗ Denied: {path}"), file=sys.stderr); sys.exit(1)
    except KeyboardInterrupt: print(Color.yellow("\nCancelled"), file=sys.stderr); sys.exit(130)

def parse_json(raw: str) -> Any:
    try: return json.loads(raw)
    except json.JSONDecodeError as e:
        print(Color.red(f"✗ JSON error: {e}"), file=sys.stderr)
        ln = raw.split("\n")
        if 0 < e.lineno <= len(ln):
            print(Color.dim(f"  Ln {e.lineno}: {ln[e.lineno-1]}"), file=sys.stderr)
            if e.colno > 0: print(Color.red(" " * (e.colno + 2) + "^"), file=sys.stderr)
        sys.exit(1)

def write_out(code: str, path: str | None) -> None:
    if path is None: print(code)
    else:
        try:
            out = os.path.abspath(path)
            with open(out, "w", encoding="utf-8") as f: f.write(code)
            print(Color.green(f"✓ Written: {out}"), file=sys.stderr)
        except PermissionError: print(Color.red(f"✗ Denied: {path}"), file=sys.stderr); sys.exit(1)
        except OSError as e: print(Color.red(f"✗ IO error: {e}"), file=sys.stderr); sys.exit(1)

def mk_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="json2v", description="JSON → V struct generator (prod)", formatter_class=argparse.RawDescriptionHelpFormatter, epilog="Lint: V001-006, V010-014, V020, V099 | Fix: --lint --fix | Strict: --strict")
    g = p.add_argument_group("I/O")
    g.add_argument("-i", "--input", metavar="FILE", help="Input JSON")
    g.add_argument("-o", "--output", metavar="FILE", help="Output V file")
    g.add_argument("--root", default="Root", metavar="NAME", help="Root struct name")
    g.add_argument("--lint", action="store_true", help="Enable lint checks")
    g.add_argument("--fix", action="store_true", help="Auto-fix naming issues")
    g.add_argument("--dry-run", action="store_true", help="Lint only, skip output")
    g.add_argument("-v", "--verbose", action="store_true", help="Verbose diagnostics")
    g.add_argument("--no-color", action="store_true", help="Disable colors")
    g.add_argument("--strict", action="store_true", help="Warnings as errors")
    p.add_argument("--version", action="version", version="json2v 2.0-prod")
    return p

def main() -> None:
    args = mk_parser().parse_args()
    if args.no_color: Color.ENABLED = False
    if args.fix and not args.lint: args.lint = True
    if args.dry_run and not args.lint: args.lint = True
    raw = read_in(args.input)
    data = parse_json(raw)
    issues: list[Issue] = []
    if not isinstance(data, dict):
        issues.append(Issue(Level.ERROR, "V020", "Root must be object", "<root>", "Ensure input is {...}"))
        print(rpt(issues, args.verbose), file=sys.stderr)
        sys.exit(1)
    code, gi = gen(data, args.root, args.fix)
    issues.extend(gi)
    if args.lint and issues: print(rpt(issues, args.verbose), file=sys.stderr)
    if args.strict:
        ec = sum(1 for i in issues if i.level == Level.ERROR)
        wc = sum(1 for i in issues if i.level == Level.WARN)
        if ec or wc:
            if not args.dry_run: write_out(code, args.output)
            print(Color.red(f"✗ Strict: {ec} err, {wc} warn"), file=sys.stderr)
            sys.exit(1)
    if args.dry_run:
        if not issues: print(Color.green("✓ Dry-run passed"), file=sys.stderr)
        elif any(i.level == Level.ERROR for i in issues): sys.exit(1)
        return
    write_out(code, args.output)
    if args.lint and any(i.level == Level.ERROR for i in issues): sys.exit(1)

if __name__ == "__main__": main()

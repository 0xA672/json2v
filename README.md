# json2v

**JSON → V struct generator (enhanced)**

A CLI tool that reads JSON and emits ready‑to‑compile V struct definitions.  
Built‑in lint checks catch naming issues, reserved words, type conflicts and more, while `--fix` can automatically repair many common problems.

## Features

- Smart type inference – list element types, null/optional types, nested structs
- Lint diagnostics – naming conventions, reserved words, duplicate fields, type conflicts
- Auto‑fix – camelCase → snake_case, reserved word escaping, null‑type suggestions
- Colored terminal output, verbose & dry‑run modes, and strict‑mode error handling
- Reads from stdin or file; writes to stdout or file

## Quick start

Requires Python 3.8 or later – zero dependencies outside the standard library.

```bash
# From stdin
echo '{"name":"Alice","age":30}' | python3 json2v.py

# From a file, output to another file
python3 json2v.py -i data.json -o output.v

# Lint + auto‑fix
python3 json2v.py -i data.json --lint --fix
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `-i, --input FILE` | stdin | Input JSON file |
| `-o, --output FILE` | stdout | Output V file |
| `--root NAME` | `Root` | Root struct name |
| `--lint` | off | Enable lint diagnostics |
| `--fix` | off | Auto‑fix lint issues (implies `--lint`) |
| `--dry-run` | off | Only lint, no code output (implies `--lint`) |
| `-v, --verbose` | off | Show detailed diagnostics and suggestions |
| `--no-color` | off | Disable colored terminal output |
| `--strict` | off | Treat warnings as errors; exit code 1 on any warning |
| `--version` | | Show version |

## Lint diagnostic codes

| Code | Severity | Description |
|------|----------|-------------|
| V001 | Warning | Empty list – cannot infer element type |
| V002 | Warning | List contains mixed element types |
| V003 | Warning | Field value is `null` – cannot determine type |
| V004 | Error | Value type cannot be mapped to a V type |
| V010 | Error/Warning | Field name is a V reserved word |
| V011 | Error/Warning | Field name conflicts with a built‑in V type |
| V012 | Warning | Field name is not snake_case |
| V013 | Error/Warning | Field name starts with a digit |
| V014 | Error | Name collision after auto‑fix |
| V020 | Error | JSON root is not an object |

## Example

**Input (`data.json`)**

```json
{
  "userName": "Alice",
  "userAge": 30,
  "isActive": true,
  "metadata": {
    "lastLogin": "2026-05-01",
    "score": 42.5
  },
  "tags": ["admin", "moderator"],
  "profile": null,
  "items": [
    {"id": 1, "value": "one"},
    {"id": 2, "value": "two"}
  ]
}
```

**Command**

```bash
python3 json2v.py -i data.json --lint --fix
```

**Output (`stdout`)**

```v
import json

pub struct Root {
    [json: userName]
    mut user_name string
    [json: userAge]
    mut user_age int
    [json: isActive]
    mut is_active bool
    [json: metadata]
    mut metadata struct {
        [json: lastLogin]
        mut last_login string
        [json: score]
        mut score f64
    }
    [json: tags]
    mut tags []string
    [json: profile]
    mut profile ?any
    [json: items]
    mut items []Item
}

pub struct Item {
    [json: id]
    mut id int
    [json: value]
    mut value string
}
```

**Lint report (`stderr`)**

```
══════════════════════════════════════════════════════
  Lint Diagnostic Report
══════════════════════════════════════════════════════

  ⚠ Warnings (2)
    [V012] Field 'Root.userName' is not snake_case, automatically converted -> 'user_name'
      Location: Root.userName
      Suggestion: auto-fix: userName -> user_name
    [V003] Field 'Root.profile' has null value, unable to determine concrete type
      Location: Root.profile
      Suggestion: Manually replace '?any' with a concrete optional type, e.g. '?string'

  Total: 2 warning(s)
══════════════════════════════════════════════════════
```

## License

MIT – see [LICENSE](LICENSE).

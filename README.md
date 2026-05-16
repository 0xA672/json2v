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

## Installation

### Requirements
- Python 3.8 or higher (no external dependencies)

### Recommended: install as a system command

Create a `setup.py` file in the same directory as `json2v.py`:

```python
from setuptools import setup

setup(
    name='json2v',
    version='2.1',
    py_modules=['json2v'],
    entry_points={
        'console_scripts': ['json2v=json2v:main'],
    },
    python_requires='>=3.8',
)
```

Then install with pip:

```bash
pip install .
```

Now you can invoke the tool globally:

```bash
json2v -i data.json -o output.v
```

### Alternative: manual placement

Make the script executable and move it into your `PATH`:

```bash
chmod +x json2v.py
sudo cp json2v.py /usr/local/bin/json2v
```

After that, `json2v` works from any terminal.

## Quick start

```bash
# From stdin
echo '{"name":"Alice","age":30}' | json2v

# From a file, output to another file
json2v -i data.json -o output.v

# Lint + auto‑fix with verbose diagnostics
json2v -i data.json --lint --fix -v
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
| V003 | Warning | Field value is `null` – cannot determine concrete type |
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
json2v -i data.json --lint --fix -v
```

**Generated V code (`stdout`)**

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

**Lint report (`stderr`, with `-v`)**

```
══════════════════════════════════════════════════════
  Lint Report
══════════════════════════════════════════════════════

  ⚠ Warnings (2)
    [V012] 'Root.userName' invalid naming
      Path: Root.userName
      Fix: -> user_name
    [V003] Null at 'Root.profile'
      Path: Root.profile
      Fix: Replace ?any

  Total: 2 warning(s)
══════════════════════════════════════════════════════
```

## License

MIT – see [LICENSE](LICENSE).

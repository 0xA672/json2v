import json, sys

def json_to_v(key, val, indent=4):
    prefix = " " * indent
    if isinstance(val, str):
        return f"{prefix}[json: {key}]\n{prefix}mut {key} string"
    elif isinstance(val, bool):
        return f"{prefix}[json: {key}]\n{prefix}mut {key} bool"
    elif isinstance(val, int):
        return f"{prefix}[json: {key}]\n{prefix}mut {key} int"
    elif isinstance(val, float):
        return f"{prefix}[json: {key}]\n{prefix}mut {key} f64"
    elif isinstance(val, list):
        return f"{prefix}[json: {key}]\n{prefix}mut {key} []string"
    elif isinstance(val, dict):
        lines = f"{prefix}[json: {key}]\n{prefix}mut {key} struct {{\n"
        for k, v in val.items():
            lines += json_to_v(k, v, indent + 4) + "\n"
        lines += f"{prefix}}}"
        return lines

data = json.load(sys.stdin)
print("import json\n")
print("pub struct Root {")
for k, v in data.items():
    print(json_to_v(k, v, 4))
print("}")

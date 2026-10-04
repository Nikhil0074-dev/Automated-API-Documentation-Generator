#!/usr/bin/env python3
"""Generate request examples (curl, Python, JavaScript, TypeScript) from an OpenAPI spec."""
from __future__ import annotations

import argparse
import json
import pprint
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from common import ROOT, SpecLoadError, deref, iter_operations, load_config, load_document

TEMPLATE_DIR = ROOT / "templates" / "code-examples"
EXTENSIONS = {"curl": "sh", "python": "py", "javascript": "js", "typescript": "ts"}
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def render(template: str, context: dict[str, str]) -> str:
    """Single-pass {{name}} substitution (substituted text is never re-scanned)."""
    return PLACEHOLDER.sub(lambda m: str(context.get(m.group(1), m.group(0))), template)


# ----------------------------------------------------------------- schema examples
def example_from_schema(spec: dict, schema: Any, depth: int = 0) -> Any:
    if depth > 6:
        return None
    schema = deref(spec, schema)
    if not isinstance(schema, dict):
        return None
    if "example" in schema:
        return schema["example"]
    if isinstance(schema.get("examples"), list) and schema["examples"]:
        return schema["examples"][0]
    if schema.get("default") is not None:
        return schema["default"]
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    if schema.get("allOf"):
        merged: dict = {}
        for part in schema["allOf"]:
            value = example_from_schema(spec, part, depth + 1)
            if isinstance(value, dict):
                merged.update(value)
        return merged
    for key in ("anyOf", "oneOf"):
        if schema.get(key):
            options = [o for o in schema[key] if deref(spec, o).get("type") != "null"]
            return example_from_schema(spec, (options or schema[key])[0], depth + 1)

    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    if kind is None and "properties" in schema:
        kind = "object"
    if kind == "object":
        return {name: example_from_schema(spec, sub, depth + 1)
                for name, sub in (schema.get("properties") or {}).items()}
    if kind == "array":
        return [example_from_schema(spec, schema.get("items", {}), depth + 1)]
    if kind == "string":
        return {"date-time": "2024-01-01T00:00:00Z", "date": "2024-01-01",
                "uuid": "123e4567-e89b-12d3-a456-426614174000",
                "email": "user@example.com", "uri": "https://example.com"}.get(
                    schema.get("format"), "string")
    if kind in ("integer", "number"):
        if "exclusiveMinimum" in schema and isinstance(schema["exclusiveMinimum"], (int, float)):
            value = schema["exclusiveMinimum"] + 1
        else:
            value = schema.get("minimum", 1)
        return int(value) if kind == "integer" else float(value)
    if kind == "boolean":
        return True
    return None


def _media_example(spec: dict, media: dict) -> Any:
    if "example" in media:
        return media["example"]
    examples = media.get("examples")
    if isinstance(examples, dict) and examples:
        first = deref(spec, next(iter(examples.values())))
        if isinstance(first, dict) and "value" in first:
            return first["value"]
    return example_from_schema(spec, media.get("schema", {}))


# ------------------------------------------------------------------- operation data
def _auth(spec: dict, op: dict) -> tuple[dict[str, str], dict[str, str]]:
    headers: dict[str, str] = {}
    query: dict[str, str] = {}
    requirements = op.get("security", spec.get("security", [])) or []
    if not requirements:
        return headers, query
    schemes = (spec.get("components") or {}).get("securitySchemes") or {}
    for name in requirements[0]:
        scheme = deref(spec, schemes.get(name, {}))
        kind = scheme.get("type")
        if kind == "apiKey":
            target = headers if scheme.get("in") == "header" else query
            if scheme.get("in") in ("header", "query"):
                target[scheme.get("name", "api_key")] = "YOUR_API_KEY"
        elif kind == "http" and scheme.get("scheme", "").lower() == "basic":
            headers["Authorization"] = "Basic YOUR_CREDENTIALS"
        elif kind in ("http", "oauth2", "openIdConnect"):
            headers["Authorization"] = "Bearer YOUR_ACCESS_TOKEN"
    return headers, query


def _identifier(text: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_")
    return cleaned if cleaned and not cleaned[0].isdigit() else f"op_{cleaned}"


def _snake(text: str) -> str:
    text = _identifier(text)
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    return re.sub(r"_+", "_", text).lower()


def _camel(text: str) -> str:
    parts = _identifier(text).split("_")
    return parts[0][:1].lower() + parts[0][1:] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace('"', "'").replace("*/", "* /").replace("\\", "/")).strip()


def build_context(spec: dict, path: str, method: str, op: dict, base_url: str) -> dict[str, Any]:
    path_item = spec["paths"][path]
    params = [deref(spec, p) for p in (path_item.get("parameters") or []) + (op.get("parameters") or [])]
    path_values: dict[str, Any] = {}
    query: dict[str, Any] = {}
    for param in params:
        value = _media_example(spec, {"schema": param.get("schema", {}), **(
            {"example": param["example"]} if "example" in param else {})})
        if param.get("in") == "path":
            path_values[param["name"]] = 1 if value is None else value
        elif param.get("in") == "query" and param.get("required"):
            query[param["name"]] = "value" if value is None else value
    url_path = re.sub(r"\{(\w+)\}", lambda m: quote(str(path_values.get(m.group(1), "1")), safe=""), path)

    headers, auth_query = _auth(spec, op)
    query.update(auth_query)

    body = None
    request_body = deref(spec, op.get("requestBody") or {})
    content = request_body.get("content") or {}
    if content:
        ctype = "application/json" if "application/json" in content else next(iter(content))
        if ctype == "application/json":
            body = _media_example(spec, content[ctype])
            headers["Content-Type"] = "application/json"

    success = sorted(str(c) for c in (op.get("responses") or {}) if str(c).startswith("2"))
    code = success[0] if success else "200"
    resp = deref(spec, (op.get("responses") or {}).get(code, {}))
    has_body = code != "204" and bool(resp.get("content"))

    summary = _one_line(op.get("summary") or f"{method.upper()} {path}")
    op_id = op.get("operationId") or f"{method}_{path}"
    return {"method": method.upper(), "path": path, "url_path": url_path, "query": query,
            "headers": headers, "body": body, "has_body": has_body, "summary": summary,
            "operation_id": op_id, "base_url": base_url.rstrip("/")}


# --------------------------------------------------------------------- renderers
def _indent_tail(text: str, spaces: int) -> str:
    lines = text.splitlines()
    return lines[0] + "".join("\n" + " " * spaces + line for line in lines[1:])


def _full_path(ctx: dict) -> str:
    qs = urlencode(ctx["query"])
    return ctx["url_path"] + (f"?{qs}" if qs else "")


def _py(obj: Any) -> str:
    return _indent_tail(pprint.pformat(obj, indent=2, sort_dicts=False, width=70), 8)


def render_python(tmpl: str, ctx: dict) -> str:
    extra = ""
    if ctx["headers"]:
        extra += f"        headers={_py(ctx['headers'])},\n"
    if ctx["body"] is not None:
        extra += f"        json={_py(ctx['body'])},\n"
    return render(tmpl, {
        "base_url": ctx["base_url"], "func_name": _snake(ctx["operation_id"]),
        "summary": ctx["summary"], "method_lower": ctx["method"].lower(),
        "path": _full_path(ctx).replace("{", "{{").replace("}", "}}"),
        "extra_args": extra,
        "return_stmt": "    return response.json()" if ctx["has_body"] else "    return None",
    })


def _js_options(ctx: dict) -> str:
    out = ""
    if ctx["headers"]:
        out += f"    headers: {_indent_tail(json.dumps(ctx['headers'], indent=2), 4)},\n"
    if ctx["body"] is not None:
        out += f"    body: JSON.stringify({_indent_tail(json.dumps(ctx['body'], indent=2), 4)}),\n"
    return out


def _js_path(ctx: dict) -> str:
    return _full_path(ctx).replace("`", "%60").replace("${", "%24%7B")


def render_javascript(tmpl: str, ctx: dict) -> str:
    return render(tmpl, {
        "base_url": ctx["base_url"], "func_name": _camel(ctx["operation_id"]),
        "summary": ctx["summary"], "method": ctx["method"], "path": _js_path(ctx),
        "options": _js_options(ctx),
        "return_stmt": "  return response.json();" if ctx["has_body"] else "  return null;",
    })


def render_typescript(tmpl: str, ctx: dict) -> str:
    return render(tmpl, {
        "base_url": ctx["base_url"], "func_name": _camel(ctx["operation_id"]),
        "summary": ctx["summary"], "method": ctx["method"], "path": _js_path(ctx),
        "options": _js_options(ctx),
        "return_type": "unknown" if ctx["has_body"] else "null",
        "return_stmt": "  return (await response.json()) as unknown;" if ctx["has_body"]
        else "  return null;",
    })


def render_curl(tmpl: str, ctx: dict) -> str:
    url = f"{ctx['base_url']}{_full_path(ctx)}"
    command = f'curl -X {ctx["method"]} "{url}"'
    for key, value in ctx["headers"].items():
        command += f' \\\n  -H "{key}: {value}"'
    if ctx["body"] is not None:
        data = json.dumps(ctx["body"], indent=2).replace("'", "'\\''")
        command += f" \\\n  -d '{data}'"
    return render(tmpl, {"summary": ctx["summary"], "command": command})


RENDERERS = {"curl": render_curl, "python": render_python,
             "javascript": render_javascript, "typescript": render_typescript}


def generate_examples(spec: dict, languages: list[str], base_url: str | None = None) -> list[dict]:
    if base_url is None:
        servers = spec.get("servers") or [{"url": "http://localhost:8000"}]
        base_url = servers[0]["url"]
    templates = {}
    for lang in languages:
        if lang not in RENDERERS:
            raise ValueError(f"Unsupported example language: {lang}")
        templates[lang] = (TEMPLATE_DIR / f"{lang}.tmpl").read_text(encoding="utf-8")
    results = []
    for path, method, op in iter_operations(spec):
        ctx = build_context(spec, path, method, op, base_url)
        results.append({
            "operation_id": op.get("operationId") or f"{method}_{path}",
            "method": method.upper(), "path": path, "summary": ctx["summary"],
            "samples": {lang: RENDERERS[lang](templates[lang], ctx) for lang in languages},
        })
    return results


def write_examples(out_dir: Path, examples: list[dict]) -> int:
    count = 0
    for item in examples:
        for lang, code in item["samples"].items():
            target = out_dir / lang / f"{_snake(item['operation_id'])}.{EXTENSIONS[lang]}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code if code.endswith("\n") else code + "\n", encoding="utf-8")
            count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", nargs="?", help="Spec file (default: from config)")
    parser.add_argument("--config")
    parser.add_argument("--output-dir", default=str(ROOT / "dist" / "examples"))
    parser.add_argument("--languages", nargs="+")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        spec = load_document(args.spec or ROOT / config["project"]["spec_path"])
        langs = args.languages or config["examples"]["languages"]
        examples = generate_examples(spec, langs, config["docs"].get("base_url"))
    except (SpecLoadError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    n = write_examples(Path(args.output_dir), examples)
    print(f"Wrote {n} example file(s) for {len(examples)} operation(s) to {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Shared helpers for the documentation pipeline scripts."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Iterator

import yaml

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

DEFAULT_CONFIG: dict[str, Any] = {
    "project": {"spec_path": "openapi/openapi.json", "output_dir": "dist"},
    "servers": [{"url": "http://localhost:8000", "description": "Local development"}],
    "docs": {"try_it_out": False, "default_renderer": "swagger", "base_url": None},
    "examples": {"languages": ["curl", "python", "javascript", "typescript"]},
    "rules": {
        "info-description": "warn", "servers-defined": "warn", "operation-id": "error",
        "operation-id-unique": "error", "operation-summary": "error",
        "operation-description": "warn", "operation-tags": "error",
        "parameter-description": "warn", "success-response": "error",
        "security-applied": "warn", "security-unused": "warn", "external-ref": "warn",
    },
    "write_methods": ["post", "put", "patch", "delete"],
}


class SpecLoadError(Exception):
    """Raised when a spec or config file cannot be read or parsed."""


def deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    if path:
        candidates = [Path(path)]
    else:
        candidates = [ROOT / "config" / "documentation.yaml",
                      ROOT / "config" / "documentation.example.yaml"]
    for candidate in candidates:
        if candidate.is_file():
            try:
                data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                raise SpecLoadError(f"Invalid config file {candidate}: {exc}") from exc
            return deep_merge(DEFAULT_CONFIG, data)
    if path:
        raise SpecLoadError(f"Config file not found: {path}")
    return copy.deepcopy(DEFAULT_CONFIG)


def load_document(path: str | Path) -> Any:
    """Load a JSON or YAML document."""
    p = Path(path)
    if not p.is_file():
        raise SpecLoadError(f"File not found: {p}")
    text = p.read_text(encoding="utf-8")
    try:
        if p.suffix.lower() == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SpecLoadError(f"Could not parse {p}: {exc}") from exc


def dump_json(data: Any, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def dump_yaml(data: Any, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")


def iter_operations(spec: dict) -> Iterator[tuple[str, str, dict]]:
    """Yield (path, method, operation) for every operation in the spec."""
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method in HTTP_METHODS:
            op = item.get(method)
            if isinstance(op, dict):
                yield path, method, op


def resolve_pointer(spec: dict, ref: str) -> Any:
    """Resolve a local JSON pointer such as '#/components/schemas/Product'."""
    if ref == "#":
        return spec
    if not ref.startswith("#/"):
        raise KeyError(ref)
    node: Any = spec
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise KeyError(ref)
    return node


def deref(spec: dict, node: Any, max_hops: int = 20) -> Any:
    """Follow $ref chains until a concrete node is found."""
    hops = 0
    while isinstance(node, dict) and isinstance(node.get("$ref"), str):
        hops += 1
        if hops > max_hops:
            return {}
        try:
            node = resolve_pointer(spec, node["$ref"])
        except KeyError:
            return {}
    return node


def count_operations(spec: dict) -> int:
    return sum(1 for _ in iter_operations(spec))

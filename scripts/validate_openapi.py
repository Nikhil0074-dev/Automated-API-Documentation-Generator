#!/usr/bin/env python3
"""Validate an OpenAPI document: schema validity, $refs and project rules."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from common import (HTTP_METHODS, ROOT, SpecLoadError, iter_operations, load_config,
                    load_document, resolve_pointer)


@dataclass
class Issue:
    level: str      # "error" | "warning"
    rule: str
    location: str
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


def _schema_validation(spec: Any) -> list[Issue]:
    try:
        from openapi_spec_validator import validate
    except ImportError:
        return [Issue("error", "validator-missing", "$",
                      "openapi-spec-validator is not installed (pip install -r requirements.txt)")]
    try:
        validate(spec)
    except Exception as exc:  # noqa: BLE001 - library raises several exception types
        message = (str(exc).strip().splitlines() or [type(exc).__name__])[0]
        return [Issue("error", "openapi-schema", "$", message)]
    return []


def _check_refs(spec: Any, node: Any, where: str, level_for_external: str | None) -> list[Issue]:
    issues: list[Issue] = []
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            if ref.startswith("#"):
                try:
                    resolve_pointer(spec, ref)
                except KeyError:
                    issues.append(Issue("error", "invalid-ref", where,
                                        f"$ref '{ref}' does not resolve"))
            elif level_for_external:
                issues.append(Issue(level_for_external, "external-ref", where,
                                    f"external $ref '{ref}' is not checked"))
        for key, value in node.items():
            if key != "$ref":
                issues.extend(_check_refs(spec, value, f"{where}/{key}", level_for_external))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            issues.extend(_check_refs(spec, value, f"{where}/{i}", level_for_external))
    return issues


def _level(config: dict, rule: str) -> str | None:
    value = (config.get("rules") or {}).get(rule, "off")
    return {"error": "error", "warn": "warning", "warning": "warning"}.get(value)


def _project_rules(spec: dict, config: dict) -> list[Issue]:
    issues: list[Issue] = []

    def add(rule: str, location: str, message: str) -> None:
        level = _level(config, rule)
        if level:
            issues.append(Issue(level, rule, location, message))

    info = spec.get("info") or {}
    if not info.get("description"):
        add("info-description", "info", "info.description is missing")
    if not spec.get("servers"):
        add("servers-defined", "servers", "no servers are declared")

    schemes = ((spec.get("components") or {}).get("securitySchemes")) or {}
    global_security = spec.get("security") or []
    used_schemes = {name for req in global_security for name in req}
    write_methods = set(config.get("write_methods", []))
    seen_ids: dict[str, str] = {}

    for path, method, op in iter_operations(spec):
        loc = f"{method.upper()} {path}"
        op_id = op.get("operationId")
        if not op_id:
            add("operation-id", loc, "operationId is missing")
        elif op_id in seen_ids:
            add("operation-id-unique", loc,
                f"operationId '{op_id}' is already used by {seen_ids[op_id]}")
        else:
            seen_ids[op_id] = loc
        if not op.get("summary"):
            add("operation-summary", loc, "summary is missing")
        if not op.get("description"):
            add("operation-description", loc, "description is missing")
        if not op.get("tags"):
            add("operation-tags", loc, "no tags assigned")

        for param in list(op.get("parameters") or []) + \
                list((spec["paths"][path].get("parameters")) or []):
            if isinstance(param, dict) and "$ref" not in param and not param.get("description"):
                add("parameter-description", f"{loc} parameter '{param.get('name')}'",
                    "parameter description is missing")

        responses = op.get("responses") or {}
        if not any(str(code).startswith("2") for code in responses):
            add("success-response", loc, "no 2xx response is defined")

        effective = op.get("security", global_security) or []
        for req in effective:
            used_schemes.update(req)
            for name in req:
                if name not in schemes:
                    issues.append(Issue("error", "security-undefined", loc,
                                        f"security scheme '{name}' is not declared"))
        if schemes and method in write_methods and not effective:
            add("security-applied", loc, "write operation has no security requirement")

    for name in schemes:
        if name not in used_schemes:
            add("security-unused", f"components.securitySchemes.{name}",
                "security scheme is declared but never applied")
    return issues


def validate_spec(spec: Any, config: dict | None = None) -> list[Issue]:
    """Run every validation layer and return all issues found."""
    config = config or load_config()
    if not isinstance(spec, dict):
        return [Issue("error", "not-an-object", "$", "specification must be a JSON/YAML object")]
    issues = _schema_validation(spec)
    issues.extend(_check_refs(spec, spec, "#", _level(config, "external-ref")))
    if isinstance(spec.get("paths"), dict):
        try:
            issues.extend(_project_rules(spec, config))
        except Exception as exc:  # noqa: BLE001 - malformed spec: schema errors already reported
            issues.append(Issue("error", "rule-engine", "$", f"could not apply project rules: {exc}"))
    return issues


def summarize(issues: list[Issue]) -> dict:
    return {"errors": sum(i.level == "error" for i in issues),
            "warnings": sum(i.level == "warning" for i in issues),
            "issues": [i.as_dict() for i in issues]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", nargs="?", help="Spec file (default: from config)")
    parser.add_argument("--config", help="Path to documentation config YAML")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    parser.add_argument("--report", help="Write a JSON report to this path")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        spec_path = Path(args.spec) if args.spec else ROOT / config["project"]["spec_path"]
        spec = load_document(spec_path)
    except SpecLoadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    issues = validate_spec(spec, config)
    for issue in issues:
        print(f"{issue.level.upper():7} [{issue.rule}] {issue.location}: {issue.message}")
    result = summarize(issues)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Validation finished: {result['errors']} error(s), {result['warnings']} warning(s)")
    failed = result["errors"] > 0 or (args.strict and result["warnings"] > 0)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

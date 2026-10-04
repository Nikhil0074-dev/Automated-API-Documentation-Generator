#!/usr/bin/env python3
"""Build the versioned documentation site from a validated OpenAPI spec."""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from common import (ROOT, SpecLoadError, count_operations, dump_json, dump_yaml, load_config,
                    load_document)
from compare_specs import BREAKING, compare_specs, render_markdown
from generate_examples import PLACEHOLDER, generate_examples, write_examples
from validate_openapi import summarize, validate_spec

TEMPLATES = ROOT / "templates"


class BuildError(Exception):
    """Raised when the documentation cannot be built."""


def render(template: str, context: dict[str, str]) -> str:
    return PLACEHOLDER.sub(lambda m: str(context.get(m.group(1), m.group(0))), template)


def _template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _json_for_script(data: object) -> str:
    """Serialise JSON so it is safe to embed inside a <script> element."""
    return (json.dumps(data, ensure_ascii=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def version_label(spec: dict) -> str:
    match = re.match(r"\s*v?(\d+)", str(spec.get("info", {}).get("version", "")))
    return f"v{match.group(1)}" if match else "v1"


def _sort_key(entry: dict) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", entry["api_version"])[:3])


def _examples_html(examples: list[dict]) -> str:
    out = []
    for item in examples:
        out.append(f'<section><h2><span class="method">{html.escape(item["method"])}</span> '
                   f'{html.escape(item["path"])}</h2>'
                   f'<p class="sub">{html.escape(item["summary"])} '
                   f'(<code>{html.escape(item["operation_id"])}</code>)</p>')
        for i, (lang, code) in enumerate(item["samples"].items()):
            open_attr = " open" if i == 0 else ""
            out.append(f"<details{open_attr}><summary>{html.escape(lang)}</summary>"
                       f"<pre><code>{html.escape(code)}</code></pre></details>")
        out.append("</section>")
    return "\n".join(out)


def _write_site(target: Path, spec: dict, ctx: dict, examples: list[dict],
                changes_md: str, config: dict) -> None:
    target.mkdir(parents=True, exist_ok=True)
    dump_json(spec, target / "openapi.json")
    dump_yaml(spec, target / "openapi.yaml")
    try_it = bool(config["docs"].get("try_it_out"))
    base = {**ctx, "spec_json": _json_for_script(spec),
            "submit_methods": '["get","put","post","delete","patch"]' if try_it else "[]"}
    (target / "index.html").write_text(render(_template("index.html"), base), encoding="utf-8")
    (target / "redoc.html").write_text(render(_template("redoc.html"), base), encoding="utf-8")
    (target / "examples.html").write_text(
        render(_template("examples.html"), {**base, "sections": _examples_html(examples)}),
        encoding="utf-8")
    (target / "changes.md").write_text(changes_md, encoding="utf-8")
    (target / "changes.html").write_text(
        render(_template("changes.html"), {**base, "report": html.escape(changes_md)}),
        encoding="utf-8")
    write_examples(target / "examples", examples)


def _update_versions(output: Path, entry: dict, make_latest: bool, title: str) -> dict:
    index_path = output / "versions.json"
    data = {"latest": None, "versions": []}
    if index_path.is_file():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    versions = [v for v in data.get("versions", []) if v["version"] != entry["version"]]
    versions.append(entry)
    data["versions"] = sorted(versions, key=_sort_key, reverse=True)
    if make_latest or not data.get("latest"):
        data["latest"] = entry["version"]
    dump_json(data, index_path)

    rows = "\n".join(
        f'<li><a href="{html.escape(v["version"])}/">{html.escape(v["version"])}</a> '
        f'<small>API {html.escape(v["api_version"])} &middot; {v["operations"]} operation(s) '
        f'&middot; built {html.escape(v["built_at"])}</small></li>' for v in data["versions"])
    (output / "index.html").write_text(
        render(_template("versions.html"),
               {"title": html.escape(title), "latest": html.escape(str(data["latest"])), "rows": rows}),
        encoding="utf-8")
    (output / ".nojekyll").write_text("", encoding="utf-8")
    return data


def build(spec_path: Path, output: Path, config: dict, version: str | None = None,
          previous: Path | None = None, make_latest: bool = True, strict: bool = False) -> dict:
    started = time.perf_counter()
    spec = load_document(spec_path)
    issues = validate_spec(spec, config)
    result = summarize(issues)
    if result["errors"] or (strict and result["warnings"]):
        details = "; ".join(f"[{i.rule}] {i.location}: {i.message}" for i in issues
                            if i.level == "error" or strict)
        raise BuildError(f"specification failed validation: {details}")

    version = version or os.environ.get("DOCS_VERSION") or version_label(spec)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", version):
        raise BuildError(f"invalid version label: {version!r}")
    if version == "latest":
        raise BuildError("'latest' is reserved for the alias directory")

    changes_md = "# API change report\n\nNo previous specification was supplied for comparison.\n"
    breaking = 0
    if previous and Path(previous).is_file():
        old = load_document(previous)
        changes = compare_specs(old, spec)
        breaking = sum(c.severity == BREAKING for c in changes)
        changes_md = render_markdown(changes, old, spec)

    examples = generate_examples(spec, config["examples"]["languages"], config["docs"].get("base_url"))
    title = spec["info"]["title"]
    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ctx = {"title": html.escape(title), "version": html.escape(version),
           "api_version": html.escape(str(spec["info"]["version"])), "root": "../"}

    output.mkdir(parents=True, exist_ok=True)
    version_dir = output / version
    if version_dir.exists():
        shutil.rmtree(version_dir)
    _write_site(version_dir, spec, ctx, examples, changes_md, config)

    entry = {"version": version, "api_version": str(spec["info"]["version"]), "built_at": built_at,
             "operations": count_operations(spec)}
    data = _update_versions(output, entry, make_latest, title)
    if data["latest"] == version:
        latest_dir = output / "latest"
        if latest_dir.exists():
            shutil.rmtree(latest_dir)
        shutil.copytree(version_dir, latest_dir)

    report = {
        "version": version, "api_version": entry["api_version"], "built_at": built_at,
        "operations": entry["operations"], "paths": len(spec.get("paths") or {}),
        "schemas": len((spec.get("components") or {}).get("schemas") or {}),
        "examples": sum(len(e["samples"]) for e in examples),
        "validation": {"errors": result["errors"], "warnings": result["warnings"],
                       "issues": result["issues"]},
        "breaking_changes": breaking, "commit": os.environ.get("GITHUB_SHA"),
        "duration_seconds": round(time.perf_counter() - started, 3),
    }
    dump_json(report, version_dir / "build-report.json")
    if data["latest"] == version:
        shutil.copy(version_dir / "build-report.json", output / "latest" / "build-report.json")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", help="Spec file (default: from config)")
    parser.add_argument("--output", help="Site directory (default: dist). Existing versions inside are kept.")
    parser.add_argument("--config")
    parser.add_argument("--version", help="Version label, e.g. v1 (default: DOCS_VERSION or major of info.version)")
    parser.add_argument("--previous", help="Previous spec to include a change report")
    parser.add_argument("--no-latest", action="store_true", help="Do not move the 'latest' alias")
    parser.add_argument("--strict", action="store_true", help="Fail on validation warnings too")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        spec_path = Path(args.spec) if args.spec else ROOT / config["project"]["spec_path"]
        output = Path(args.output) if args.output else ROOT / config["project"]["output_dir"]
        report = build(spec_path, output, config, args.version,
                       Path(args.previous) if args.previous else None,
                       not args.no_latest, args.strict)
    except (SpecLoadError, BuildError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Built documentation '{report['version']}' (API {report['api_version']}) in {output}")
    print(f"  {report['operations']} operation(s), {report['examples']} example(s), "
          f"{report['validation']['warnings']} warning(s), {report['duration_seconds']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

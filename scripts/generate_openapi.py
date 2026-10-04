#!/usr/bin/env python3
"""Generate the OpenAPI specification from the FastAPI application."""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

from common import ROOT, SpecLoadError, dump_json, dump_yaml, iter_operations, load_config


def generate_spec(config: dict) -> dict:
    """Return the OpenAPI document produced by the application."""
    from app.main import app

    app.openapi_schema = None  # force regeneration
    spec = copy.deepcopy(app.openapi())
    if config.get("servers"):
        spec["servers"] = config["servers"]
    return spec


def _iter_api_routes(routes, prefix: str = ""):
    """Yield (methods, path) for every schema-visible APIRoute.

    Handles both flattened routers (older FastAPI) and lazily included routers
    (newer FastAPI exposes them as objects carrying an ``include_context``).
    """
    from fastapi.routing import APIRoute

    for route in routes:
        if isinstance(route, APIRoute):
            if route.include_in_schema:
                yield route.methods, prefix + route.path_format
            continue
        context = getattr(route, "include_context", None)
        router = getattr(context, "included_router", None)
        if router is not None and getattr(context, "include_in_schema", True):
            yield from _iter_api_routes(router.routes, prefix + (getattr(context, "prefix", "") or ""))


def endpoint_coverage(spec: dict) -> dict:
    """Compare routes registered in the app with operations in the spec."""
    from app.main import app

    routes = set()
    for methods, path in _iter_api_routes(app.routes):
        for method in set(methods) - {"HEAD", "OPTIONS"}:
            routes.add((method.lower(), path))
    documented = {(m, p) for p, m, _ in iter_operations(spec)}
    covered = routes & documented
    if not routes:
        return {"routes": 0, "documented": 0, "coverage_percent": None, "missing": [],
                "unavailable": True}
    return {"routes": len(routes), "documented": len(covered),
            "coverage_percent": round(len(covered) / len(routes) * 100, 1),
            "missing": sorted(f"{m.upper()} {p}" for m, p in routes - documented)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Path to documentation config YAML")
    parser.add_argument("--output-dir", default=str(ROOT / "openapi"),
                        help="Directory for openapi.json / openapi.yaml")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        spec = generate_spec(config)
    except SpecLoadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - surface any import/introspection failure
        print(f"ERROR: could not generate specification: {exc}", file=sys.stderr)
        return 1

    out = Path(args.output_dir)
    dump_json(spec, out / "openapi.json")
    dump_yaml(spec, out / "openapi.yaml")
    cov = endpoint_coverage(spec)
    print(f"Generated OpenAPI {spec.get('openapi')} for '{spec['info']['title']}' "
          f"v{spec['info']['version']}")
    print(f"  written to {out}/openapi.json and {out}/openapi.yaml")
    if cov.get("unavailable"):
        print("ERROR: could not discover application routes to measure coverage", file=sys.stderr)
        return 1
    print(f"  endpoint coverage: {cov['documented']}/{cov['routes']} ({cov['coverage_percent']}%)")
    if cov["missing"]:
        print(f"  undocumented routes: {', '.join(cov['missing'])}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

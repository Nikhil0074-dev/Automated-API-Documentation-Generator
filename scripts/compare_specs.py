#!/usr/bin/env python3
"""Compare two OpenAPI specs and report breaking / non-breaking changes."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from common import HTTP_METHODS, SpecLoadError, deref, load_document

BREAKING, WARNING, INFO = "breaking", "warning", "info"

# Explanation shown next to each finding so reviewers see *why* it matters.
RULES = {
    "endpoint-removed": "Clients calling a removed endpoint will receive 404/405.",
    "operation-id-changed": "Generated SDK method names derive from operationId.",
    "required-parameter-added": "Existing clients do not send the new required parameter.",
    "parameter-now-required": "Existing clients may omit a parameter that is now mandatory.",
    "parameter-removed": "Clients may still send the parameter; it is now ignored or rejected.",
    "request-body-now-required": "Existing clients may send no body.",
    "request-content-removed": "Clients using the removed media type will be rejected.",
    "response-removed": "Clients may rely on the removed status code.",
    "response-content-removed": "Clients may rely on the removed media type.",
    "type-changed": "Clients parse/send values using the previous type.",
    "enum-narrowed": "Values that were accepted in requests are now rejected.",
    "enum-widened": "Clients may not handle the newly returned values.",
    "constraint-tightened": "Requests valid before may now fail validation.",
    "required-request-field-added": "Existing clients do not send the new required field.",
    "request-field-now-required": "Existing clients may omit a field that is now mandatory.",
    "response-field-removed": "Clients may read a field that is no longer returned.",
    "response-field-no-longer-required": "Clients may assume a field that is no longer guaranteed.",
    "authentication-added": "Previously anonymous calls will now be rejected.",
    "authentication-changed": "Existing credentials may no longer be accepted.",
    "security-scheme-changed": "Clients must change how they send credentials.",
    "composition-changed": "anyOf/oneOf/allOf changed shape; review manually.",
    "deprecated": "Endpoint is now deprecated; plan migration.",
}


@dataclass
class Change:
    severity: str
    code: str
    location: str
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


class Comparer:
    def __init__(self, old: dict, new: dict) -> None:
        self.old, self.new = old, new
        self.changes: list[Change] = []

    def add(self, severity: str, code: str, location: str, message: str) -> None:
        self.changes.append(Change(severity, code, location, message))

    # -------------------------------------------------------------- schemas
    def schema(self, o: Any, n: Any, direction: str, loc: str, depth: int = 0) -> None:
        if depth > 8:
            return
        o, n = deref(self.old, o), deref(self.new, n)
        if not isinstance(o, dict) or not isinstance(n, dict):
            return

        for key in ("allOf", "anyOf", "oneOf"):
            if key in o or key in n:
                lo, ln = o.get(key) or [], n.get(key) or []
                if len(lo) != len(ln):
                    self.add(WARNING, "composition-changed", loc,
                             f"'{key}' changed from {len(lo)} to {len(ln)} alternative(s)")
                else:
                    for i, (a, b) in enumerate(zip(lo, ln)):
                        self.schema(a, b, direction, f"{loc}/{key}[{i}]", depth + 1)

        ot, nt = self._types(o), self._types(n)
        if ot and nt and ot != nt:
            safe = (self._subtype(ot, nt) if direction == "request" else self._subtype(nt, ot))
            self.add(INFO if safe else BREAKING, "type-changed", loc,
                     f"type changed from {sorted(ot)} to {sorted(nt)}")

        self._enum(o, n, direction, loc)
        if direction == "request":
            self._constraints(o, n, loc)
        if o.get("format") != n.get("format") and "format" in (o | n):
            self.add(WARNING, "type-changed", loc,
                     f"format changed from {o.get('format')!r} to {n.get('format')!r}")

        self._object(o, n, direction, loc, depth)
        if "items" in o and "items" in n:
            self.schema(o["items"], n["items"], direction, f"{loc}[]", depth + 1)

    @staticmethod
    def _types(s: dict) -> set[str]:
        t = s.get("type")
        return set() if t is None else ({t} if isinstance(t, str) else set(t))

    @staticmethod
    def _subtype(a: set[str], b: set[str]) -> bool:
        return all(t in b or (t == "integer" and "number" in b) for t in a)

    def _enum(self, o: dict, n: dict, direction: str, loc: str) -> None:
        oe, ne = o.get("enum"), n.get("enum")
        key = lambda v: json.dumps(v, sort_keys=True)  # noqa: E731
        if oe is not None and ne is not None:
            removed = {key(v) for v in oe} - {key(v) for v in ne}
            added = {key(v) for v in ne} - {key(v) for v in oe}
            if direction == "request" and removed:
                self.add(BREAKING, "enum-narrowed", loc,
                         f"accepted values removed: {sorted(removed)}")
            if direction == "response" and added:
                self.add(WARNING, "enum-widened", loc, f"new possible values: {sorted(added)}")
        elif oe is None and ne is not None and direction == "request":
            self.add(BREAKING, "enum-narrowed", loc, "request values are now restricted to an enum")

    def _constraints(self, o: dict, n: dict, loc: str) -> None:
        def num(v: Any) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool)

        for key in ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties"):
            a, b = o.get(key), n.get(key)
            if num(b) and (a is None or (num(a) and b > a)):
                self.add(BREAKING, "constraint-tightened", loc, f"{key} changed from {a} to {b}")
        for key in ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties"):
            a, b = o.get(key), n.get(key)
            if num(b) and (a is None or (num(a) and b < a)):
                self.add(BREAKING, "constraint-tightened", loc, f"{key} changed from {a} to {b}")

    def _object(self, o: dict, n: dict, direction: str, loc: str, depth: int) -> None:
        po, pn = o.get("properties") or {}, n.get("properties") or {}
        ro, rn = set(o.get("required") or []), set(n.get("required") or [])
        for name in po.keys() - pn.keys():
            p = f"{loc}.{name}"
            if direction == "response":
                self.add(BREAKING, "response-field-removed", p, "field removed from response")
            elif n.get("additionalProperties") is False:
                self.add(BREAKING, "type-changed", p, "field removed and extra fields are forbidden")
            else:
                self.add(INFO, "parameter-removed", p, "request field removed")
        for name in pn.keys() - po.keys():
            p = f"{loc}.{name}"
            if direction == "request" and name in rn:
                self.add(BREAKING, "required-request-field-added", p, "new required request field")
            else:
                self.add(INFO, "field-added", p, f"new optional {direction} field")
        for name in po.keys() & pn.keys():
            p = f"{loc}.{name}"
            if direction == "request" and name in rn and name not in ro:
                self.add(BREAKING, "request-field-now-required", p, "request field is now required")
            if direction == "response" and name in ro and name not in rn:
                self.add(BREAKING, "response-field-no-longer-required", p,
                         "response field is no longer guaranteed")
            self.schema(po[name], pn[name], direction, p, depth + 1)

    # ----------------------------------------------------------- operations
    def _params(self, spec: dict, item: dict, op: dict) -> dict[tuple, dict]:
        params = {}
        for raw in (item.get("parameters") or []) + (op.get("parameters") or []):
            p = deref(spec, raw)
            if isinstance(p, dict) and "name" in p:
                params[(p.get("in"), p["name"])] = p
        return params

    def _security(self, spec: dict, op: dict) -> set[frozenset]:
        reqs = op.get("security", spec.get("security", [])) or []
        return {frozenset(r) for r in reqs if r} if any(r for r in reqs) else set()

    def operation(self, path: str, method: str, oi: dict, ni: dict, oo: dict, no: dict) -> None:
        loc = f"{method.upper()} {path}"
        if oo.get("operationId") != no.get("operationId"):
            self.add(WARNING, "operation-id-changed", loc,
                     f"operationId changed from {oo.get('operationId')!r} to {no.get('operationId')!r}")
        if no.get("deprecated") and not oo.get("deprecated"):
            self.add(WARNING, "deprecated", loc, "operation marked as deprecated")

        po, pn = self._params(self.old, oi, oo), self._params(self.new, ni, no)
        for key in po.keys() - pn.keys():
            self.add(INFO, "parameter-removed", f"{loc} {key[0]} parameter '{key[1]}'",
                     "parameter removed")
        for key in pn.keys() - po.keys():
            if pn[key].get("required"):
                self.add(BREAKING, "required-parameter-added", f"{loc} {key[0]} parameter '{key[1]}'",
                         "new required parameter")
            else:
                self.add(INFO, "parameter-added", f"{loc} {key[0]} parameter '{key[1]}'",
                         "new optional parameter")
        for key in po.keys() & pn.keys():
            ploc = f"{loc} {key[0]} parameter '{key[1]}'"
            if pn[key].get("required") and not po[key].get("required"):
                self.add(BREAKING, "parameter-now-required", ploc, "parameter is now required")
            self.schema(po[key].get("schema", {}), pn[key].get("schema", {}), "request", ploc)

        self._request_body(loc, oo, no)
        self._responses(loc, oo, no)
        self._auth(loc, oo, no)

    def _request_body(self, loc: str, oo: dict, no: dict) -> None:
        ob, nb = deref(self.old, oo.get("requestBody") or {}), deref(self.new, no.get("requestBody") or {})
        if not ob and nb:
            sev = BREAKING if nb.get("required") else INFO
            self.add(sev, "request-body-now-required" if sev == BREAKING else "request-body-added",
                     f"{loc} request body", "request body added")
            return
        if ob and not nb:
            self.add(INFO, "parameter-removed", f"{loc} request body", "request body removed")
            return
        if not ob:
            return
        if nb.get("required") and not ob.get("required"):
            self.add(BREAKING, "request-body-now-required", f"{loc} request body",
                     "request body is now required")
        oc, nc = ob.get("content") or {}, nb.get("content") or {}
        for ctype in oc.keys() - nc.keys():
            self.add(BREAKING, "request-content-removed", f"{loc} request body", f"{ctype} no longer accepted")
        for ctype in oc.keys() & nc.keys():
            self.schema(oc[ctype].get("schema", {}), nc[ctype].get("schema", {}), "request",
                        f"{loc} request body ({ctype})")

    def _responses(self, loc: str, oo: dict, no: dict) -> None:
        ro, rn = oo.get("responses") or {}, no.get("responses") or {}
        for code in sorted(ro.keys() - rn.keys()):
            self.add(BREAKING, "response-removed", f"{loc} response {code}", "response removed")
        for code in sorted(rn.keys() - ro.keys()):
            self.add(INFO, "response-added", f"{loc} response {code}", "response added")
        for code in sorted(ro.keys() & rn.keys()):
            a, b = deref(self.old, ro[code]), deref(self.new, rn[code])
            ca, cb = a.get("content") or {}, b.get("content") or {}
            for ctype in ca.keys() - cb.keys():
                self.add(BREAKING, "response-content-removed", f"{loc} response {code}",
                         f"{ctype} no longer returned")
            for ctype in ca.keys() & cb.keys():
                self.schema(ca[ctype].get("schema", {}), cb[ctype].get("schema", {}), "response",
                            f"{loc} response {code} ({ctype})")

    def _auth(self, loc: str, oo: dict, no: dict) -> None:
        so, sn = self._security(self.old, oo), self._security(self.new, no)
        if so != sn:
            if not so and sn:
                self.add(BREAKING, "authentication-added", loc, "operation now requires authentication")
            elif so and not sn:
                self.add(INFO, "authentication-removed", loc, "operation no longer requires authentication")
            elif so <= sn:
                self.add(INFO, "authentication-added", loc, "additional authentication options accepted")
            else:
                self.add(BREAKING, "authentication-changed", loc,
                         "accepted authentication options changed")
        schemes_o = (self.old.get("components") or {}).get("securitySchemes") or {}
        schemes_n = (self.new.get("components") or {}).get("securitySchemes") or {}
        for combo in so & sn:
            for name in combo:
                if schemes_o.get(name) != schemes_n.get(name):
                    self.add(BREAKING, "security-scheme-changed", f"{loc} scheme '{name}'",
                             "security scheme definition changed")

    # ------------------------------------------------------------------ run
    def run(self) -> list[Change]:
        po, pn = self.old.get("paths") or {}, self.new.get("paths") or {}
        for path in po:
            for method in HTTP_METHODS:
                if isinstance(po[path].get(method), dict):
                    if path not in pn or not isinstance(pn[path].get(method), dict):
                        self.add(BREAKING, "endpoint-removed", f"{method.upper()} {path}",
                                 "endpoint removed")
                    else:
                        self.operation(path, method, po[path], pn[path],
                                       po[path][method], pn[path][method])
        for path in pn:
            for method in HTTP_METHODS:
                if isinstance(pn[path].get(method), dict) and not (
                        path in po and isinstance(po[path].get(method), dict)):
                    self.add(INFO, "endpoint-added", f"{method.upper()} {path}", "endpoint added")
        return self.changes


def compare_specs(old: dict, new: dict) -> list[Change]:
    return Comparer(old, new).run()


def render_markdown(changes: list[Change], old: dict | None, new: dict) -> str:
    counts = {s: sum(c.severity == s for c in changes) for s in (BREAKING, WARNING, INFO)}
    old_v = (old or {}).get("info", {}).get("version", "n/a")
    new_v = new.get("info", {}).get("version", "n/a")
    lines = ["# API change report", "",
             f"Comparing version **{old_v}** with **{new_v}**.", "",
             f"**{counts[BREAKING]}** breaking, **{counts[WARNING]}** warning(s), "
             f"**{counts[INFO]}** non-breaking change(s).", ""]
    titles = {BREAKING: "Breaking changes", WARNING: "Warnings (review recommended)",
              INFO: "Non-breaking changes"}
    for sev in (BREAKING, WARNING, INFO):
        group = [c for c in changes if c.severity == sev]
        if not group:
            continue
        lines += [f"## {titles[sev]}", ""]
        for c in group:
            why = RULES.get(c.code)
            lines.append(f"- `{c.location}` - {c.message} (`{c.code}`)" + (f". _{why}_" if why else ""))
        lines.append("")
    if not changes:
        lines.append("No differences detected.")
    lines.append("_A change is only flagged as breaking when it can break an existing client under "
                 "the compatibility rules above; review warnings in context._")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old", help="Previous (baseline) spec")
    parser.add_argument("new", help="Newly generated spec")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", help="Write the report to this file instead of stdout")
    parser.add_argument("--fail-on-breaking", action="store_true")
    args = parser.parse_args(argv)

    try:
        new = load_document(args.new)
    except SpecLoadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not Path(args.old).is_file():
        print(f"No baseline spec at {args.old}; skipping comparison (first release).")
        return 0
    try:
        old = load_document(args.old)
    except SpecLoadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    changes = compare_specs(old, new)
    if args.format == "json":
        report = json.dumps([c.as_dict() for c in changes], indent=2)
    else:
        report = render_markdown(changes, old, new)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(report)
    breaking = sum(c.severity == BREAKING for c in changes)
    print(f"{breaking} breaking change(s) detected.", file=sys.stderr)
    return 1 if (args.fail_on_breaking and breaking) else 0


if __name__ == "__main__":
    sys.exit(main())

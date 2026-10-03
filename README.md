# Automated API Documentation Generator

Generates, validates, versions and publishes API documentation straight from source code,
driven by GitHub Actions. The reference implementation documents a **FastAPI** product API
and deploys to **GitHub Pages**.

```text
push / PR -> GitHub Actions -> FastAPI introspection -> OpenAPI 3.1 spec
          -> validation (schema + $refs + project rules) -> breaking-change report
          -> Swagger UI + ReDoc + code examples -> versioned static site -> gh-pages
```

## Features

| Objective | Where |
|---|---|
| OpenAPI generation from the framework schema | `scripts/generate_openapi.py` |
| Spec validation (syntax, `$ref`s, configurable rules) | `scripts/validate_openapi.py` |
| Swagger UI + ReDoc, searchable, "Try it out" **off by default** | `scripts/build_docs.py`, `templates/` |
| curl / Python / JavaScript / TypeScript examples (placeholder credentials) | `scripts/generate_examples.py` |
| Breaking-change detection with explanations | `scripts/compare_specs.py` |
| Versioned docs (`v1/`, `v2/`, `latest/`), old versions preserved | `scripts/build_docs.py` |
| Build report (time, counts, warnings, breaking changes) | `dist/<version>/build-report.json` |
| CI (PR-safe) and separate protected deployment | `.github/workflows/` |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m pytest                                       # run the test suite
python scripts/generate_openapi.py                     # -> openapi/openapi.json + .yaml
python scripts/validate_openapi.py                     # exit code 1 on errors
python scripts/build_docs.py                           # -> dist/
python -m http.server -d dist 8080                     # open http://localhost:8080

uvicorn app.main:app --reload                          # run the sample API itself
```

Write operations need `X-API-Key`; the sample accepts the value of `PRODUCT_API_KEY`
(default `change-me` - always set your own outside of local development).

## Scripts

```bash
python scripts/generate_openapi.py [--output-dir DIR] [--config FILE]
python scripts/validate_openapi.py [SPEC] [--strict] [--report FILE]
python scripts/build_docs.py [--spec SPEC] [--output DIR] [--version v1] [--previous OLD_SPEC]
                             [--no-latest] [--strict]
python scripts/generate_examples.py [SPEC] [--output-dir DIR] [--languages curl python]
python scripts/compare_specs.py OLD NEW [--format markdown|json] [--fail-on-breaking]
```

All scripts return a non-zero exit code on failure, so they can gate CI.

## Configuration

Copy `config/documentation.example.yaml` to `config/documentation.yaml` (the example is used
if the copy is missing). You can set servers, the example languages and base URL,
whether "Try it out" is enabled, and the severity of each validation rule
(`error` fails the build, `warn` only reports, `off` disables).

## CI/CD design

* **`api-docs.yml`** - runs on every push to `main` and every pull request with a
  *read-only* token: tests, generation, validation, breaking-change report (written to the job
  summary), preview build uploaded as an artifact. It never publishes.
  Set the repository variable `FAIL_ON_BREAKING=true` to fail PRs that introduce breaking changes.
* **`deploy-docs.yml`** - runs only on `main` and `v*` tags. The build job is read-only; only the
  `deploy` job has `contents: write`. It restores the existing `gh-pages` content, adds/updates the
  version directory and pushes, so earlier versions are kept. A tag `v2.1.0` publishes to `v2/`.
* Enable GitHub Pages: *Settings -> Pages -> Deploy from a branch -> `gh-pages`*.
* For production, pin third-party actions to commit SHAs and protect `main`.

### Releasing a new API version

1. Change the API and bump `API_VERSION` in `app/main.py`.
2. `python scripts/generate_openapi.py` and commit `openapi/`.
3. Merge to `main` (docs update), then tag: `git tag v2.0.0 && git push --tags`.

## Adding another backend framework

The pipeline only needs an OpenAPI document. Replace `generate_spec()` in
`scripts/generate_openapi.py` with an adapter for your framework (or point
`project.spec_path` at a hand-written `openapi.yaml`); every later step is framework-independent.

## Project layout

```text
app/        sample FastAPI API (routes, schemas, services)
scripts/    generate / validate / build / examples / compare
templates/  HTML pages and code-example templates
openapi/    committed spec (baseline for breaking-change detection)
config/     documentation settings
tests/      pytest suite (API, spec, validation, examples, comparison, build)
.github/    CI and deployment workflows
docs/       description of the generated site
```

## Security notes

* "Try it out" is disabled by default; enable it only for safe, approved environments.
* Examples contain placeholders only; never put real credentials in descriptions or examples.
* PR workflows use a read-only token and no secrets; deployment is a separate job.
* Spec content is escaped before being embedded in HTML pages.
* Do not publish internal APIs to a public site - host privately or restrict access.

## Limitations

* Extraction quality depends on the framework and on explicit annotations; business logic is
  not inferred.
* The comparer applies documented heuristics; review warnings in context.
* Generated examples are templates, not tested SDKs; they may need auth/environment changes.
* Swagger UI/ReDoc scripts load from a CDN.
* A valid contract does not guarantee the implementation is bug-free.

## Possible extensions

GitHub App for multiple repositories, a metadata dashboard (FastAPI + SQLite), OpenAPI Generator
SDKs, Spectral linting, additional framework adapters, PR preview deployments.

MIT licensed.

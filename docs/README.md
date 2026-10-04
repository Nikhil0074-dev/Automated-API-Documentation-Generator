# Generated documentation layout

`scripts/build_docs.py` produces a static site (default output: `dist/`, or the
`gh-pages` branch in CI):

```text
site/
├── index.html          # version picker
├── versions.json       # machine-readable list of published versions
├── latest/             # copy of the most recent version
├── v1/
│   ├── index.html      # Swagger UI
│   ├── redoc.html      # ReDoc
│   ├── examples.html   # curl / Python / JavaScript / TypeScript examples
│   ├── changes.html    # breaking-change report vs. the previous spec
│   ├── openapi.json / openapi.yaml
│   ├── examples/       # example files per language
│   └── build-report.json   # build metrics and validation results
└── v2/ ...
```

`build-report.json` records build time, endpoint/schema/example counts,
validation errors and warnings, the number of breaking changes and the commit.
Swagger UI and ReDoc scripts load from the jsDelivr CDN, so viewing the pages
requires internet access. The spec is embedded inline, so the pages also work
from `file://`.

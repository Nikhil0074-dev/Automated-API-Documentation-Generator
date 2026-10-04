import json

import pytest

from build_docs import BuildError, build
from common import dump_json


def test_build_creates_versioned_site(spec, config, tmp_path):
    src = tmp_path / "spec.json"
    dump_json(spec, src)
    out = tmp_path / "site"
    report = build(src, out, config)
    assert report["version"] == "v1" and report["operations"] == 5
    for name in ("index.html", "redoc.html", "examples.html", "changes.html",
                 "openapi.json", "openapi.yaml", "build-report.json"):
        assert (out / "v1" / name).is_file() and (out / "latest" / name).is_file()
    assert (out / "index.html").is_file() and (out / ".nojekyll").is_file()
    page = (out / "v1" / "index.html").read_text()
    assert "SwaggerUIBundle" in page and "listProducts" in page
    assert "supportedSubmitMethods: []" in page   # try-it-out disabled by default
    assert "{{" not in page.replace("{{}}", "")


def test_try_it_out_can_be_enabled(spec, config, tmp_path):
    src = tmp_path / "spec.json"
    dump_json(spec, src)
    config["docs"]["try_it_out"] = True
    build(src, tmp_path / "site", config)
    assert '"post"' in (tmp_path / "site" / "v1" / "index.html").read_text()


def test_old_versions_are_preserved(spec, spec_copy, config, tmp_path):
    out = tmp_path / "site"
    v1 = tmp_path / "v1.json"; dump_json(spec, v1)
    spec_copy["info"]["version"] = "2.0.0"
    v2 = tmp_path / "v2.json"; dump_json(spec_copy, v2)
    build(v1, out, config)
    build(v2, out, config, previous=v1)
    data = json.loads((out / "versions.json").read_text())
    assert [v["version"] for v in data["versions"]] == ["v2", "v1"] and data["latest"] == "v2"
    assert (out / "v1" / "index.html").is_file() and (out / "v2" / "index.html").is_file()
    assert "2.0.0" in (out / "latest" / "index.html").read_text()


def test_no_latest_keeps_alias(spec, spec_copy, config, tmp_path):
    out = tmp_path / "site"
    v1 = tmp_path / "v1.json"; dump_json(spec, v1)
    build(v1, out, config)
    spec_copy["info"]["version"] = "2.0.0"
    v2 = tmp_path / "v2.json"; dump_json(spec_copy, v2)
    build(v2, out, config, make_latest=False)
    assert json.loads((out / "versions.json").read_text())["latest"] == "v1"


def test_change_report_included(spec, spec_copy, config, tmp_path):
    del spec_copy["paths"]["/products"]["get"]
    old, new = tmp_path / "old.json", tmp_path / "new.json"
    dump_json(spec, old); dump_json(spec_copy, new)
    report = build(new, tmp_path / "site", config, previous=old)
    assert report["breaking_changes"] >= 1
    assert "endpoint-removed" in (tmp_path / "site" / "v1" / "changes.md").read_text()


def test_invalid_spec_blocks_build(spec_copy, config, tmp_path):
    del spec_copy["paths"]["/products"]["get"]["operationId"]
    src = tmp_path / "bad.json"; dump_json(spec_copy, src)
    with pytest.raises(BuildError):
        build(src, tmp_path / "site", config)
    assert not (tmp_path / "site" / "v1").exists()


def test_bad_version_label_rejected(spec, config, tmp_path):
    src = tmp_path / "spec.json"; dump_json(spec, src)
    for label in ("../evil", "latest", "a b"):
        with pytest.raises(BuildError):
            build(src, tmp_path / "site", config, version=label)


def test_spec_content_cannot_break_out_of_script(spec_copy, config, tmp_path):
    spec_copy["info"]["description"] = "</script><script>alert(1)</script>"
    src = tmp_path / "s.json"; dump_json(spec_copy, src)
    build(src, tmp_path / "site", config)
    assert "</script><script>alert(1)" not in (tmp_path / "site" / "v1" / "index.html").read_text()

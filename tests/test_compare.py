import copy

import pytest

from compare_specs import BREAKING, compare_specs, render_markdown


def codes(changes, severity=BREAKING):
    return {c.code for c in changes if c.severity == severity}


def test_identical_specs_have_no_changes(spec):
    assert compare_specs(spec, copy.deepcopy(spec)) == []


def test_removed_endpoint_is_breaking(spec, spec_copy):
    del spec_copy["paths"]["/products/{product_id}"]["delete"]
    changes = compare_specs(spec, spec_copy)
    assert "endpoint-removed" in codes(changes)
    assert any(c.location == "DELETE /products/{product_id}" for c in changes)


def test_removed_response_is_breaking(spec, spec_copy):
    del spec_copy["paths"]["/products/{product_id}"]["get"]["responses"]["404"]
    assert "response-removed" in codes(compare_specs(spec, spec_copy))


def test_new_required_request_field_is_breaking(spec, spec_copy):
    schema = spec_copy["components"]["schemas"]["ProductCreate"]
    schema["properties"]["sku"] = {"type": "string"}
    schema["required"].append("sku")
    assert "required-request-field-added" in codes(compare_specs(spec, spec_copy))


def test_optional_request_field_is_not_breaking(spec, spec_copy):
    spec_copy["components"]["schemas"]["ProductCreate"]["properties"]["sku"] = {"type": "string"}
    changes = compare_specs(spec, spec_copy)
    assert codes(changes) == set()
    assert "field-added" in codes(changes, "info")


def test_removed_required_response_field_is_breaking(spec, spec_copy):
    schema = spec_copy["components"]["schemas"]["Product"]
    schema["required"].remove("name")
    assert "response-field-no-longer-required" in codes(compare_specs(spec, spec_copy))
    del schema["properties"]["name"]
    assert "response-field-removed" in codes(compare_specs(spec, spec_copy))


def test_new_required_parameter_is_breaking(spec, spec_copy):
    spec_copy["paths"]["/products"]["get"]["parameters"].append(
        {"name": "region", "in": "query", "required": True, "schema": {"type": "string"}})
    assert "required-parameter-added" in codes(compare_specs(spec, spec_copy))


def test_parameter_type_change_is_breaking(spec, spec_copy):
    for p in spec_copy["paths"]["/products"]["get"]["parameters"]:
        if p["name"] == "limit":
            p["schema"] = {"type": "string"}
    assert "type-changed" in codes(compare_specs(spec, spec_copy))


def test_request_enum_narrowing_is_breaking(spec, spec_copy):
    old = copy.deepcopy(spec)
    old["components"]["schemas"]["ProductCreate"]["properties"]["name"]["enum"] = ["a", "b"]
    spec_copy["components"]["schemas"]["ProductCreate"]["properties"]["name"]["enum"] = ["a"]
    assert "enum-narrowed" in codes(compare_specs(old, spec_copy))


def test_tightened_constraint_is_breaking(spec, spec_copy):
    spec_copy["components"]["schemas"]["ProductCreate"]["properties"]["name"]["maxLength"] = 10
    assert "constraint-tightened" in codes(compare_specs(spec, spec_copy))


def test_authentication_changes(spec, spec_copy):
    del spec_copy["paths"]["/products"]["post"]["security"]
    assert "authentication-removed" in codes(compare_specs(spec, spec_copy), "info")
    assert "authentication-added" in codes(compare_specs(spec_copy, spec))


def test_new_endpoint_is_non_breaking(spec, spec_copy):
    spec_copy["paths"]["/health"] = {"get": {"operationId": "health", "responses": {"200": {"description": "ok"}}}}
    changes = compare_specs(spec, spec_copy)
    assert codes(changes) == set() and "endpoint-added" in codes(changes, "info")


def test_markdown_report_explains_rules(spec, spec_copy):
    del spec_copy["paths"]["/products"]["get"]
    report = render_markdown(compare_specs(spec, spec_copy), spec, spec_copy)
    assert "Breaking changes" in report and "GET /products" in report and "404" in report


def test_cli_fail_on_breaking(spec, spec_copy, tmp_path):
    import compare_specs as cs
    from common import dump_json
    del spec_copy["paths"]["/products"]["get"]
    old, new = tmp_path / "old.json", tmp_path / "new.json"
    dump_json(spec, old); dump_json(spec_copy, new)
    assert cs.main([str(old), str(new)]) == 0
    assert cs.main([str(old), str(new), "--fail-on-breaking"]) == 1
    assert cs.main([str(tmp_path / "none.json"), str(new), "--fail-on-breaking"]) == 0

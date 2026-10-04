import pytest

from generate_openapi import endpoint_coverage
from validate_openapi import validate_spec


def errors(issues):
    return [i for i in issues if i.level == "error"]


def test_generated_spec_is_valid(spec, config):
    assert spec["openapi"].startswith("3.")
    assert errors(validate_spec(spec, config)) == []


def test_full_endpoint_coverage(spec):
    cov = endpoint_coverage(spec)
    assert cov["routes"] == 5
    assert cov["coverage_percent"] == 100.0 and cov["missing"] == []


def test_expected_operations(spec):
    ids = {op["operationId"] for item in spec["paths"].values()
           for op in item.values() if isinstance(op, dict)}
    assert ids == {"listProducts", "getProduct", "createProduct", "updateProduct", "deleteProduct"}


def test_security_applied_to_write_operations(spec):
    assert "ApiKeyAuth" in spec["components"]["securitySchemes"]
    assert "security" not in spec["paths"]["/products"]["get"]
    for path, method in [("/products", "post"), ("/products/{product_id}", "put"),
                         ("/products/{product_id}", "delete")]:
        assert spec["paths"][path][method]["security"] == [{"ApiKeyAuth": []}]


def test_missing_operation_id_fails(spec_copy, config):
    del spec_copy["paths"]["/products"]["get"]["operationId"]
    assert any(i.rule == "operation-id" for i in errors(validate_spec(spec_copy, config)))


def test_duplicate_operation_id_fails(spec_copy, config):
    spec_copy["paths"]["/products"]["post"]["operationId"] = "listProducts"
    assert any(i.rule == "operation-id-unique" for i in errors(validate_spec(spec_copy, config)))


def test_invalid_ref_fails(spec_copy, config):
    schema = spec_copy["paths"]["/products"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    schema["items"] = {"$ref": "#/components/schemas/DoesNotExist"}
    assert any(i.rule == "invalid-ref" for i in errors(validate_spec(spec_copy, config)))


def test_malformed_document_fails(config):
    assert errors(validate_spec({"openapi": "3.1.0"}, config))
    assert errors(validate_spec([], config))


def test_missing_description_is_configurable(spec_copy, config):
    del spec_copy["paths"]["/products"]["get"]["description"]
    warn = [i for i in validate_spec(spec_copy, config) if i.rule == "operation-description"]
    assert warn and warn[0].level == "warning"
    config["rules"]["operation-description"] = "error"
    assert any(i.rule == "operation-description" for i in errors(validate_spec(spec_copy, config)))
    config["rules"]["operation-description"] = "off"
    assert not [i for i in validate_spec(spec_copy, config) if i.rule == "operation-description"]


def test_unused_security_scheme_warns(spec_copy, config):
    for item in spec_copy["paths"].values():
        for op in item.values():
            if isinstance(op, dict):
                op.pop("security", None)
    rules = {i.rule for i in validate_spec(spec_copy, config)}
    assert {"security-unused", "security-applied"} <= rules


def test_cli_exit_codes(tmp_path, capsys):
    import json
    import validate_openapi
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert validate_openapi.main([str(bad)]) == 1
    assert "ERROR" in capsys.readouterr().err
    assert validate_openapi.main([str(tmp_path / "missing.json")]) == 1
    good = tmp_path / "good.json"
    from common import load_config
    from generate_openapi import generate_spec
    good.write_text(json.dumps(generate_spec(load_config())))
    assert validate_openapi.main([str(good)]) == 0

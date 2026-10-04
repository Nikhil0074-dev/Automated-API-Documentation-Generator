import ast
import shutil
import subprocess

import pytest

from generate_examples import generate_examples, write_examples


@pytest.fixture()
def examples(spec):
    return generate_examples(spec, ["curl", "python", "javascript", "typescript"])


def test_one_example_per_operation(examples):
    assert len(examples) == 5
    assert {e["method"] for e in examples} == {"GET", "POST", "PUT", "DELETE"}


def test_python_examples_are_valid_syntax(examples):
    for item in examples:
        ast.parse(item["samples"]["python"])


def test_javascript_examples_pass_node_check(examples, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    for item in examples:
        f = tmp_path / f"{item['operation_id']}.mjs"
        f.write_text(item["samples"]["javascript"])
        result = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_examples_contain_expected_request_details(examples):
    by_id = {e["operation_id"]: e["samples"] for e in examples}
    assert 'curl -X GET "https://api.example.com/products"' in by_id["listProducts"]["curl"]
    assert "/products/1" in by_id["getProduct"]["python"]
    create = by_id["createProduct"]
    assert "X-API-Key: YOUR_API_KEY" in create["curl"]
    assert "Mechanical Keyboard" in create["javascript"]
    assert "requests.post(" in create["python"]
    assert 'method: "DELETE"' in by_id["deleteProduct"]["typescript"]
    assert "Promise<null>" in by_id["deleteProduct"]["typescript"]


def test_no_real_credentials_in_examples(examples):
    assert "change-me" not in "".join(c for e in examples for c in e["samples"].values())


def test_write_examples(examples, tmp_path):
    assert write_examples(tmp_path, examples) == 20
    assert (tmp_path / "python" / "list_products.py").is_file()
    assert (tmp_path / "javascript" / "list_products.js").is_file()


def test_unsupported_language_rejected(spec):
    with pytest.raises(ValueError):
        generate_examples(spec, ["cobol"])

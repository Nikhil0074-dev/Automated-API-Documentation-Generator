import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from common import load_config  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_store():
    from app.services.product_service import product_service
    product_service.reset()
    yield


@pytest.fixture()
def config():
    return load_config()


@pytest.fixture()
def spec(config):
    from generate_openapi import generate_spec
    return generate_spec(config)


@pytest.fixture()
def spec_copy(spec):
    return copy.deepcopy(spec)

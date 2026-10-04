"""Sample FastAPI application documented by the generator."""
from fastapi import FastAPI

from app.routes import products

API_VERSION = "1.0.0"

app = FastAPI(
    title="Example Product API",
    version=API_VERSION,
    description=(
        "API for managing products.\n\n"
        "Read operations are public. Write operations require an API key sent in the "
        "`X-API-Key` header."
    ),
    license_info={"name": "MIT", "identifier": "MIT"},
    openapi_tags=[{"name": "products", "description": "Create, read, update and delete products."}],
)
app.include_router(products.router)

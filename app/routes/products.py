"""Product endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from app.schemas.product import ErrorResponse, Product, ProductCreate
from app.services.auth import require_api_key
from app.services.product_service import product_service

router = APIRouter(prefix="/products", tags=["products"])

NOT_FOUND = {404: {"model": ErrorResponse, "description": "Product not found."}}
UNAUTHORIZED = {401: {"model": ErrorResponse, "description": "Missing or invalid API key."}}
ProductId = Annotated[int, Path(ge=1, description="Unique product identifier.")]


@router.get(
    "", response_model=list[Product], operation_id="listProducts",
    summary="List products",
    description="Return a paginated list of products, optionally filtered by stock status.",
    responses={200: {"description": "Product list retrieved successfully."}},
)
def list_products(
    skip: Annotated[int, Query(ge=0, description="Number of products to skip.")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Maximum number of products to return.")] = 20,
    in_stock: Annotated[bool | None, Query(description="Filter by stock availability.")] = None,
):
    return product_service.list(skip, limit, in_stock)


@router.get(
    "/{product_id}", response_model=Product, operation_id="getProduct",
    summary="Get a product", description="Return a single product by its identifier.",
    responses={200: {"description": "Product retrieved successfully."}, **NOT_FOUND},
)
def get_product(product_id: ProductId):
    product = product_service.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post(
    "", response_model=Product, status_code=status.HTTP_201_CREATED,
    operation_id="createProduct", summary="Create a product",
    description="Create a new product. Requires a valid API key.",
    dependencies=[Depends(require_api_key)],
    responses={201: {"description": "Product created successfully."}, **UNAUTHORIZED},
)
def create_product(payload: ProductCreate):
    return product_service.create(payload)


@router.put(
    "/{product_id}", response_model=Product, operation_id="updateProduct",
    summary="Replace a product",
    description="Replace all fields of an existing product. Requires a valid API key.",
    dependencies=[Depends(require_api_key)],
    responses={200: {"description": "Product updated successfully."}, **UNAUTHORIZED, **NOT_FOUND},
)
def update_product(product_id: ProductId, payload: ProductCreate):
    product = product_service.replace(product_id, payload)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.delete(
    "/{product_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
    operation_id="deleteProduct", summary="Delete a product",
    description="Permanently delete a product. Requires a valid API key.",
    dependencies=[Depends(require_api_key)],
    responses={204: {"description": "Product deleted successfully."}, **UNAUTHORIZED, **NOT_FOUND},
)
def delete_product(product_id: ProductId):
    if not product_service.delete(product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

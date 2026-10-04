"""Pydantic schemas for the Product API."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    """Payload used to create or fully replace a product."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Mechanical Keyboard",
                    "description": "Hot-swappable 75% keyboard with brown switches.",
                    "price": 89.99,
                    "in_stock": True,
                }
            ]
        }
    )

    name: str = Field(
        ..., min_length=1, max_length=120,
        description="Human-readable product name.",
        examples=["Mechanical Keyboard"],
    )
    description: str | None = Field(
        default=None, max_length=1000,
        description="Optional long-form product description.",
    )
    price: float = Field(
        ..., gt=0,
        description="Unit price in the store currency. Must be greater than zero.",
        examples=[89.99],
    )
    in_stock: bool = Field(
        default=True, description="Whether the product can currently be purchased."
    )


class Product(ProductCreate):
    """A product stored in the catalogue."""

    id: int = Field(..., ge=1, description="Unique product identifier.", examples=[1])


class ErrorResponse(BaseModel):
    """Standard error body returned by the API."""

    detail: str = Field(..., description="Human-readable error message.",
                        examples=["Product not found"])

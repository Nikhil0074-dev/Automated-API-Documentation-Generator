"""In-memory product store (stands in for a real database)."""
from __future__ import annotations

from app.schemas.product import Product, ProductCreate


class ProductService:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._items: dict[int, Product] = {}
        self._next_id = 1
        self.create(ProductCreate(name="Wireless Mouse", description="2.4 GHz ergonomic mouse.",
                                  price=24.5, in_stock=True))
        self.create(ProductCreate(name="USB-C Hub", description="7-in-1 aluminium hub.",
                                  price=39.0, in_stock=False))

    def list(self, skip: int = 0, limit: int = 20, in_stock: bool | None = None) -> list[Product]:
        items = list(self._items.values())
        if in_stock is not None:
            items = [p for p in items if p.in_stock == in_stock]
        return items[skip: skip + limit]

    def get(self, product_id: int) -> Product | None:
        return self._items.get(product_id)

    def create(self, data: ProductCreate) -> Product:
        product = Product(id=self._next_id, **data.model_dump())
        self._items[product.id] = product
        self._next_id += 1
        return product

    def replace(self, product_id: int, data: ProductCreate) -> Product | None:
        if product_id not in self._items:
            return None
        product = Product(id=product_id, **data.model_dump())
        self._items[product_id] = product
        return product

    def delete(self, product_id: int) -> bool:
        return self._items.pop(product_id, None) is not None


product_service = ProductService()

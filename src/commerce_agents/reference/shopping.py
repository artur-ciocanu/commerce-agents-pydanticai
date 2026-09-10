# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Shopping contracts transplanted from commerce-agents without its model runtime."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Unavailable(Exception):
    """A product exists but cannot be bought in the current context."""


class Product(BaseModel):
    product_id: str
    title: str
    brand: str | None = None
    price: float
    currency: str = "USD"
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int | None = None
    image_url: str | None = None
    category: str | None = None
    labels: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    in_stock: bool = True
    short_description: str | None = None
    options: dict[str, list[str]] = Field(default_factory=dict)
    option_values: dict[str, str] = Field(default_factory=dict)
    variant_of: str | None = None

    @property
    def has_options(self) -> bool:
        return bool(self.options)


class ProductDetails(Product):
    long_description: str | None = None
    specs: dict[str, str] = Field(default_factory=dict)
    review_highlights: list[str] = Field(default_factory=list)
    variants: list[Product] = Field(default_factory=list)


class SearchFilters(BaseModel):
    category: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    min_rating: float | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    sort: Literal["relevance", "price_asc", "price_desc", "rating"] = "relevance"


class CartItem(BaseModel):
    product_id: str
    title: str
    price: float
    quantity: int = Field(ge=1)
    image_url: str | None = None
    option_values: dict[str, str] = Field(default_factory=dict)
    variant_of: str | None = None

    @property
    def line_total(self) -> float:
        return round(self.price * self.quantity, 2)


class Cart(BaseModel):
    items: list[CartItem] = Field(default_factory=list)
    currency: str = "USD"

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def subtotal(self) -> float:
        return round(sum(item.line_total for item in self.items), 2)


class UserPreferences(BaseModel):
    user_id: str
    display_name: str | None = None
    loyalty_tier: str | None = None
    default_location: str | None = None
    preferences: dict[str, str] = Field(default_factory=dict)


class OrderStatus(StrEnum):
    PROCESSING = "processing"
    SHIPPED = "shipped"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    DELAYED = "delayed"
    CANCELLED = "cancelled"
    RETURN_INITIATED = "return_initiated"
    REFUNDED = "refunded"


class OrderItem(BaseModel):
    product_id: str
    title: str
    quantity: int
    price: float
    option_values: dict[str, str] = Field(default_factory=dict)
    variant_of: str | None = None


class Order(BaseModel):
    order_id: str
    status: OrderStatus
    placed_at: datetime
    items: list[OrderItem] = Field(default_factory=list)
    total: float
    currency: str = "USD"
    estimated_delivery: str | None = None
    tracking_url: str | None = None


class Policy(BaseModel):
    policy_id: str
    title: str
    category: str | None = None
    content: str


class DisclosureRow(BaseModel):
    label: str
    value: str
    note: str | None = None


class Disclosure(BaseModel):
    title: str
    product_id: str
    rows: list[DisclosureRow]
    sources: list[str] = Field(default_factory=list)
    footnotes: list[str] = Field(default_factory=list)


class FulfillmentOption(BaseModel):
    method: Literal["delivery", "pickup", "shipping"]
    eta: str
    fee: float = 0.0
    location: str | None = None


class ShoppingSessionContext(BaseModel):
    session_id: str
    user_id: str = "demo-user"
    page: dict[str, Any] = Field(default_factory=dict)

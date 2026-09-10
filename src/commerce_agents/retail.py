"""Small in-memory retail vertical used to exercise both commerce roles end to end."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .merchant import merchant_tools
from .runtime import CommerceAgent, ToolContract
from .shopping import (
    Cart,
    CartItem,
    FulfillmentOption,
    Policy,
    Product,
    ProductDetails,
    shopping_tools,
)

Role = Literal["shopping", "merchant"]

MEMORY_TOOL = ToolContract(
    "save_memory",
    "Save a durable, non-sensitive customer preference or constraint for this session.",
    {
        "type": "object",
        "properties": {
            "key": {"type": "string", "maxLength": 64},
            "value": {"type": "string", "maxLength": 240},
        },
        "required": ["key", "value"],
        "additionalProperties": False,
    },
)


CATALOG = (
    Product(
        product_id="TR-100",
        title="Trail Tent 2P",
        category="camping",
        price=229.0,
        in_stock=True,
        attributes={"inventory": "8", "capacity": "2"},
    ),
    Product(
        product_id="TR-200",
        title="Alpine Tent 3P",
        category="camping",
        price=349.0,
        in_stock=True,
        attributes={"inventory": "3", "capacity": "3"},
    ),
    Product(
        product_id="PK-100",
        title="Day Hike Pack",
        category="outdoors",
        price=89.0,
        in_stock=True,
        attributes={"inventory": "14", "volume": "24L"},
    ),
)


@dataclass
class RetailExecutor:
    """In-memory typed retail backend for the shopping reference agent."""

    cart: dict[str, int] = field(default_factory=dict)

    async def search_products(
        self, query: str, filters: dict[str, Any] | None, limit: int
    ) -> list[Product]:
        terms = query.lower().split()
        products = [
            product
            for product in CATALOG
            if all(term in f"{product.title} {product.category}".lower() for term in terms)
        ]
        if filters and (maximum := filters.get("max_price")) is not None:
            products = [product for product in products if product.price <= float(maximum)]
        return products[:limit]

    async def get_product_details(self, product_id: str) -> ProductDetails | None:
        product = self._product(product_id)
        if product is None:
            return None
        return ProductDetails(
            **product.model_dump(),
            long_description=f"A dependable {product.title.lower()} for everyday outdoor use.",
            specs=product.attributes,
            review_highlights=["Easy to use", "Durable materials"],
        )

    async def get_cart(self, session_id: str) -> Cart:
        del session_id
        return Cart(
            items=[
                CartItem(
                    product_id=product.product_id,
                    title=product.title,
                    price=product.price,
                    quantity=quantity,
                )
                for product_id, quantity in self.cart.items()
                if (product := self._product(product_id)) is not None
            ]
        )

    async def add_to_cart(self, session_id: str, product_id: str, quantity: int) -> Cart:
        del session_id
        product = self._product(product_id)
        if product is None or not product.in_stock:
            raise ValueError("Product is unavailable")
        self.cart[product_id] = self.cart.get(product_id, 0) + quantity
        return await self.get_cart("")

    async def update_cart_item(self, session_id: str, product_id: str, quantity: int) -> Cart:
        del session_id
        if product_id in self.cart:
            self.cart[product_id] = quantity
        return await self.get_cart("")

    async def remove_from_cart(self, session_id: str, product_id: str) -> Cart:
        del session_id
        self.cart.pop(product_id, None)
        return await self.get_cart("")

    async def search_policies(self, query: str) -> list[Policy]:
        policies = [
            Policy(
                policy_id="returns", title="Returns", content="Return unused items within 30 days."
            ),
            Policy(
                policy_id="shipping",
                title="Shipping",
                content="Standard delivery takes 2-5 business days.",
            ),
        ]
        return [
            policy
            for policy in policies
            if query.lower() in f"{policy.title} {policy.content}".lower()
        ]

    async def get_fulfillment_options(self, product_ids: list[str]) -> list[FulfillmentOption]:
        del product_ids
        return [FulfillmentOption(method="delivery", eta="2-5 business days", fee=0.0)]

    @staticmethod
    def _product(product_id: str) -> Product | None:
        return next((product for product in CATALOG if product.product_id == product_id), None)


def build_retail_agent(role: Role, model: str) -> CommerceAgent:
    if role == "shopping":
        return CommerceAgent(
            model=model,
            instructions=(
                "You are a concise retail shopping assistant. Use tools for catalog facts and "
                "availability. Never invent a product, price, or cart result."
            ),
            tools=(*shopping_tools(), MEMORY_TOOL),
        )
    return CommerceAgent(
        model=model,
        instructions=(
            "You are a retail merchant assistant. Use tools for operational facts. Every write "
            "must be staged for a human host; never claim a staged change is applied."
        ),
        tools=(*merchant_tools(), MEMORY_TOOL),
    )

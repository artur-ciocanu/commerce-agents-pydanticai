"""Typed shopping contracts, backend boundary, and provenance-gated executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .events import AgentEvent, ToolOutcome
from .fencing import Fence
from .runtime import ToolContract
from .skills import SkillRegistry

SHOPPING_FENCE = Fence("storefront_data")


class Product(BaseModel):
    product_id: str
    title: str
    price: float = Field(gt=0)
    category: str | None = None
    brand: str | None = None
    in_stock: bool = True
    short_description: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
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


class CartItem(BaseModel):
    product_id: str
    title: str
    price: float
    quantity: int = Field(ge=1)


class Cart(BaseModel):
    items: list[CartItem] = Field(default_factory=list)
    currency: str = "USD"

    @property
    def subtotal(self) -> float:
        return round(sum(item.price * item.quantity for item in self.items), 2)


class Policy(BaseModel):
    policy_id: str
    title: str
    content: str


class FulfillmentOption(BaseModel):
    method: str
    eta: str | None = None
    fee: float | None = None


class ShoppingSessionState(BaseModel):
    seen_products: dict[str, Product] = Field(default_factory=dict)

    def remember_products(self, products: list[Product]) -> None:
        self.seen_products.update({product.product_id: product for product in products})


class StorefrontBackend(Protocol):
    async def search_products(
        self, query: str, filters: dict[str, Any] | None, limit: int
    ) -> list[Product]: ...
    async def get_product_details(self, product_id: str) -> ProductDetails | None: ...
    async def get_cart(self, session_id: str) -> Cart: ...
    async def add_to_cart(self, session_id: str, product_id: str, quantity: int) -> Cart: ...
    async def update_cart_item(self, session_id: str, product_id: str, quantity: int) -> Cart: ...
    async def remove_from_cart(self, session_id: str, product_id: str) -> Cart: ...
    async def search_policies(self, query: str) -> list[Policy]: ...
    async def get_fulfillment_options(self, product_ids: list[str]) -> list[FulfillmentOption]: ...


def shopping_tools(skills: SkillRegistry | None = None) -> tuple[ToolContract, ...]:
    skill_names = skills.names if skills else []
    return (
        ToolContract(
            "load_skill",
            "Load instructions for a named commerce flow.",
            _schema({"skill_name": {"type": "string", "enum": skill_names}}, ["skill_name"]),
        ),
        ToolContract(
            "search_products",
            "Search the catalog using the customer's constraints.",
            _schema(
                {
                    "query": {"type": "string"},
                    "filters": {"type": "object"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 24},
                },
                ["query"],
            ),
        ),
        ToolContract(
            "get_product_details",
            "Read the full record for a product returned this session.",
            _schema({"product_id": {"type": "string"}}, ["product_id"]),
        ),
        ToolContract("get_cart", "Read the active cart.", _schema({})),
        ToolContract(
            "add_to_cart",
            "Add a previously seen, in-stock product to the cart.",
            _schema(
                {
                    "product_id": {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                ["product_id"],
            ),
        ),
        ToolContract(
            "update_cart_item",
            "Set the quantity for an existing cart line.",
            _schema(
                {
                    "product_id": {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                ["product_id", "quantity"],
            ),
        ),
        ToolContract(
            "remove_from_cart",
            "Remove a product from the cart.",
            _schema({"product_id": {"type": "string"}}, ["product_id"]),
        ),
        ToolContract(
            "search_policies",
            "Search store policies.",
            _schema({"query": {"type": "string"}}, ["query"]),
        ),
        ToolContract(
            "get_orders",
            "Read recent orders for the active customer.",
            _schema({"limit": {"type": "integer", "minimum": 1, "maximum": 5}}),
        ),
        ToolContract(
            "get_order_status",
            "Read the status of one order belonging to the active customer.",
            _schema({"order_id": {"type": "string"}}, ["order_id"]),
        ),
        ToolContract(
            "get_fulfillment_options",
            "Read delivery or pickup options for products.",
            _schema(
                {"product_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 12}},
                ["product_ids"],
            ),
        ),
    )


@dataclass
class ShoppingExecutor:
    backend: StorefrontBackend
    session_id: str
    state: ShoppingSessionState = field(default_factory=ShoppingSessionState)
    skills: SkillRegistry = field(default_factory=lambda: SkillRegistry([]))

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        if name == "load_skill":
            text = self.skills.get_instructions(str(arguments["skill_name"]))
            return ToolOutcome(text or "Unknown skill.", is_error=text is None)
        if name == "search_products":
            products = await self.backend.search_products(
                arguments["query"], arguments.get("filters"), int(arguments.get("limit", 8))
            )
            self.state.remember_products(products)
            return self._fenced([product.model_dump() for product in products])
        if name == "get_product_details":
            product = await self.backend.get_product_details(arguments["product_id"])
            if product is None:
                return ToolOutcome("Product not found.", is_error=True)
            self.state.remember_products([product, *product.variants])
            return self._fenced(product.model_dump())
        if name in {"add_to_cart", "update_cart_item", "remove_from_cart"}:
            product_id = str(arguments["product_id"])
            product = self.state.seen_products.get(product_id)
            if product is None:
                return ToolOutcome(
                    "Read this product from the catalog before changing the cart.",
                    blocked="provenance",
                )
            if name == "add_to_cart" and product.has_options:
                return ToolOutcome(
                    "Read this product's details and add a specific in-stock variant.",
                    blocked="variant_selection",
                )
            cart = await self._cart_change(name, product_id, arguments)
            return self._cart_outcome(cart)
        if name == "get_cart":
            return self._cart_outcome(await self.backend.get_cart(self.session_id), emit=False)
        if name == "search_policies":
            policies = await self.backend.search_policies(arguments["query"])
            return self._fenced([policy.model_dump() for policy in policies])
        if name == "get_orders":
            get_orders = getattr(self.backend, "get_orders", None)
            if get_orders is None:
                return ToolOutcome("Orders are not available for this storefront.", is_error=True)
            return self._fenced(await get_orders(int(arguments.get("limit", 5))))
        if name == "get_order_status":
            get_order = getattr(self.backend, "get_order", None)
            if get_order is None:
                return ToolOutcome("Orders are not available for this storefront.", is_error=True)
            order = await get_order(arguments["order_id"])
            return self._fenced(order) if order else ToolOutcome("Order not found.", is_error=True)
        if name == "get_fulfillment_options":
            options = await self.backend.get_fulfillment_options(list(arguments["product_ids"]))
            return self._fenced([option.model_dump() for option in options])
        return ToolOutcome(f"Unsupported shopping tool: {name}", is_error=True)

    async def _cart_change(self, name: str, product_id: str, arguments: dict[str, Any]) -> Cart:
        if name == "add_to_cart":
            return await self.backend.add_to_cart(
                self.session_id, product_id, int(arguments["quantity"])
            )
        if name == "update_cart_item":
            return await self.backend.update_cart_item(
                self.session_id, product_id, int(arguments["quantity"])
            )
        return await self.backend.remove_from_cart(self.session_id, product_id)

    def _cart_outcome(self, cart: Cart, *, emit: bool = True) -> ToolOutcome:
        payload = {
            "items": [item.model_dump() for item in cart.items],
            "subtotal": cart.subtotal,
            "currency": cart.currency,
        }
        events = (AgentEvent("cart_update", payload),) if emit else ()
        return ToolOutcome(SHOPPING_FENCE.fence_payload(payload), events)

    @staticmethod
    def _fenced(payload: Any) -> ToolOutcome:
        return ToolOutcome(SHOPPING_FENCE.fence_payload(payload))


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }

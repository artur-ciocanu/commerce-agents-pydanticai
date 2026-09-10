"""Small in-memory retail vertical used to exercise both commerce roles end to end."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .events import AgentEvent, ToolOutcome
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


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


SHOPPING_TOOLS = (
    ToolContract(
        "search_products",
        "Search the catalog for products matching the customer's request.",
        _schema({"query": {"type": "string", "description": "Customer search terms."}}, ["query"]),
    ),
    ToolContract(
        "get_product",
        "Get current price and availability for a product before recommending it.",
        _schema({"product_id": {"type": "string"}}, ["product_id"]),
    ),
    ToolContract(
        "add_to_cart",
        "Add an in-stock product to the session cart.",
        _schema(
            {"product_id": {"type": "string"}, "quantity": {"type": "integer", "minimum": 1}},
            ["product_id", "quantity"],
        ),
    ),
    ToolContract("get_cart", "Read the session cart.", _schema({})),
)

MERCHANT_TOOLS = (
    ToolContract(
        "get_business_snapshot", "Read current retail performance and inventory.", _schema({})
    ),
    ToolContract(
        "stage_price_update",
        "Stage, but never apply, a price change for host approval.",
        _schema(
            {
                "product_id": {"type": "string"},
                "new_price": {"type": "number", "exclusiveMinimum": 0},
            },
            ["product_id", "new_price"],
        ),
    ),
    ToolContract("get_pending_changes", "List staged changes awaiting host approval.", _schema({})),
)


@dataclass
class RetailExecutor:
    """Retail backend boundary. Merchant writes are staged and never applied by the model."""

    cart: dict[str, int] = field(default_factory=dict)
    staged_changes: list[dict[str, Any]] = field(default_factory=list)

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        if name == "search_products":
            query = str(arguments["query"]).lower()
            matches = [
                product
                for product in CATALOG
                if query in f"{product.title} {product.category}".lower()
            ]
            return ToolOutcome(self._products(matches))
        if name == "get_product":
            product = self._product(arguments["product_id"])
            return ToolOutcome(
                self._products([product]) if product else "Product not found.", is_error=not product
            )
        if name == "add_to_cart":
            product = self._product(arguments["product_id"])
            quantity = int(arguments["quantity"])
            if not product or quantity > product.inventory:
                return ToolOutcome("That quantity is unavailable.", blocked="availability")
            self.cart[product.product_id] = self.cart.get(product.product_id, 0) + quantity
            return ToolOutcome(
                f"Added {quantity} x {product.title}.",
                (AgentEvent("cart_update", {"items": self.cart.copy()}),),
            )
        if name == "get_cart":
            return ToolOutcome(str({"items": self.cart, "subtotal": self._subtotal()}))
        if name == "get_business_snapshot":
            return ToolOutcome(
                str({"revenue_last_30_days": 18420, "orders": 96, "low_inventory": ["TR-200"]})
            )
        if name == "stage_price_update":
            product = self._product(arguments["product_id"])
            if not product:
                return ToolOutcome("Product not found.", is_error=True)
            change = {
                "change_id": f"chg-{len(self.staged_changes) + 1:04}",
                "product_id": product.product_id,
                "from_price": product.price,
                "to_price": float(arguments["new_price"]),
                "status": "staged",
            }
            self.staged_changes.append(change)
            return ToolOutcome(
                f"Staged {change['change_id']} for host approval.",
                (AgentEvent("change_update", {"change": change}),),
            )
        if name == "get_pending_changes":
            return ToolOutcome(str(self.staged_changes))
        return ToolOutcome(f"Unsupported tool: {name}", is_error=True)

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

    @staticmethod
    def _products(products: list[Product]) -> str:
        return str(
            [
                {
                    "product_id": product.product_id,
                    "title": product.title,
                    "price": product.price,
                    "in_stock": product.in_stock,
                }
                for product in products
            ]
        )

    def _subtotal(self) -> float:
        return sum(
            (self._product(product_id) or CATALOG[0]).price * quantity
            for product_id, quantity in self.cart.items()
        )


def build_retail_agent(role: Role, model: str) -> CommerceAgent:
    if role == "shopping":
        return CommerceAgent(
            model=model,
            instructions=(
                "You are a concise retail shopping assistant. Use tools for catalog facts and "
                "availability. Never invent a product, price, or cart result."
            ),
            tools=shopping_tools(),
        )
    return CommerceAgent(
        model=model,
        instructions=(
            "You are a retail merchant assistant. Use tools for operational facts. Every write "
            "must be staged for a human host; never claim a staged change is applied."
        ),
        tools=MERCHANT_TOOLS,
    )

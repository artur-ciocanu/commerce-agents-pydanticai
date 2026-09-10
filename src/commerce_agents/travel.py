"""Travel catalog backend built on the shared provenance-gated shopping executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .shopping import Cart, CartItem, FulfillmentOption, Policy, Product, ProductDetails

TRAVEL_CATALOG = (
    Product(
        product_id="HTL-LIS-01",
        title="Alfama Courtyard Hotel",
        category="hotel",
        price=189.0,
        attributes={"city": "Lisbon", "price_unit": "per night", "refundable": "yes"},
    ),
    Product(
        product_id="FLT-LIS-01",
        title="London to Lisbon Morning Flight",
        category="flight",
        price=214.0,
        attributes={"origin_city": "London", "destination_city": "Lisbon", "cabin": "economy"},
    ),
    Product(
        product_id="ACT-LIS-01",
        title="Lisbon Food and Fado Evening",
        category="activity",
        price=72.0,
        attributes={"city": "Lisbon", "duration": "3 hours"},
    ),
)


@dataclass
class TravelBackend:
    """Small in-memory travel storefront with the shared shopping backend surface."""

    cart: dict[str, int] = field(default_factory=dict)

    async def search_products(
        self, query: str, filters: dict[str, Any] | None, limit: int
    ) -> list[Product]:
        terms = query.lower().split()
        products = [
            product
            for product in TRAVEL_CATALOG
            if all(term in self._searchable(product) for term in terms)
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
            long_description=f"A bookable {product.category} option for your trip.",
            specs=product.attributes,
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
        if self._product(product_id) is None:
            raise ValueError("Travel option is unavailable")
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
                policy_id="cancellation",
                title="Cancellation",
                content="Refundable hotel bookings can be cancelled until the stated deadline.",
            ),
            Policy(
                policy_id="booking",
                title="Booking",
                content="Travel prices and availability are confirmed only at booking.",
            ),
        ]
        return [
            policy
            for policy in policies
            if query.lower() in f"{policy.title} {policy.content}".lower()
        ]

    async def get_fulfillment_options(self, product_ids: list[str]) -> list[FulfillmentOption]:
        del product_ids
        return [
            FulfillmentOption(method="booking confirmation", eta="Issued after checkout", fee=0)
        ]

    @staticmethod
    def _product(product_id: str) -> Product | None:
        return next(
            (product for product in TRAVEL_CATALOG if product.product_id == product_id), None
        )

    @staticmethod
    def _searchable(product: Product) -> str:
        return " ".join(
            [product.title, product.category or "", *product.attributes.values()]
        ).lower()

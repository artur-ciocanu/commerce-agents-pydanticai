"""Adapt transplanted commerce-agents storefront backends to the PydanticAI host."""

from __future__ import annotations

from typing import Any

from ..shopping import Cart, CartItem, FulfillmentOption, Policy, Product, ProductDetails
from .entertainment import MockTicketing
from .retail import MockRetail
from .shopping import SearchFilters, ShoppingSessionContext
from .telecom import MockTelecom
from .travel import MockTravel


class RetailBackendAdapter:
    """The source MockRetail API behind the target's provider-neutral tool executor."""

    def __init__(self, session_id: str, backend: Any | None = None) -> None:
        self._backend = backend or MockRetail()
        self._session = ShoppingSessionContext(session_id=session_id)

    async def search_products(
        self, query: str, filters: dict[str, Any] | None, limit: int
    ) -> list[Product]:
        source_filters = SearchFilters.model_validate(filters or {})
        products = await self._backend.search_products(self._session, query, source_filters, limit)
        return [Product.model_validate(product.model_dump()) for product in products]

    async def get_product_details(self, product_id: str) -> ProductDetails | None:
        product = await self._backend.get_product_details(self._session, product_id)
        return ProductDetails.model_validate(product.model_dump()) if product else None

    async def get_cart(self, session_id: str) -> Cart:
        del session_id
        return self._cart(await self._backend.get_cart(self._session))

    async def add_to_cart(self, session_id: str, product_id: str, quantity: int) -> Cart:
        del session_id
        return self._cart(await self._backend.add_to_cart(self._session, product_id, quantity))

    async def update_cart_item(self, session_id: str, product_id: str, quantity: int) -> Cart:
        del session_id
        return self._cart(await self._backend.update_cart_item(self._session, product_id, quantity))

    async def remove_from_cart(self, session_id: str, product_id: str) -> Cart:
        del session_id
        return self._cart(await self._backend.remove_from_cart(self._session, product_id))

    async def search_policies(self, query: str) -> list[Policy]:
        policies = await self._backend.search_policies(self._session, query)
        return [Policy.model_validate(policy.model_dump()) for policy in policies]

    async def get_fulfillment_options(self, product_ids: list[str]) -> list[FulfillmentOption]:
        options = await self._backend.get_fulfillment_options(self._session, product_ids)
        return [FulfillmentOption.model_validate(option.model_dump()) for option in options]

    @staticmethod
    def _cart(source: Any) -> Cart:
        return Cart(
            items=[CartItem.model_validate(item.model_dump()) for item in source.items],
            currency=source.currency,
        )


class TravelBackendAdapter(RetailBackendAdapter):
    """The source MockTravel API behind the target's provider-neutral tool executor."""

    def __init__(self, session_id: str, backend: MockTravel | None = None) -> None:
        super().__init__(session_id, backend or MockTravel())


class TelecomBackendAdapter(RetailBackendAdapter):
    """The source MockTelecom API behind the target's provider-neutral tool executor."""

    def __init__(self, session_id: str, backend: MockTelecom | None = None) -> None:
        super().__init__(session_id, backend or MockTelecom())


class EntertainmentBackendAdapter(RetailBackendAdapter):
    """The source ticketing backend, including its live availability and hold state."""

    def __init__(self, session_id: str, backend: MockTicketing | None = None) -> None:
        super().__init__(session_id, backend or MockTicketing())

"""Provider-neutral merchant tools and staged-change lifecycle.

The model never writes storefront state directly.  This module owns the source
merchant contract's read provenance, bounded staged writes, and host approval
gate; vertical adapters provide the live catalog behind it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .events import AgentEvent, ToolOutcome
from .fencing import Fence
from .runtime import ToolContract
from .shopping import Product

MERCHANT_FENCE = Fence("merchant_data")


class ChangeKind(StrEnum):
    LISTING_UPDATE = "listing_update"
    PRICE_UPDATE = "price_update"
    INVENTORY_ACTION = "inventory_action"
    PROMOTION = "promotion"
    CAMPAIGN = "campaign"


class ChangeStatus(StrEnum):
    STAGED = "staged"
    APPLIED = "applied"
    DISCARDED = "discarded"


class ActorKind(StrEnum):
    OPERATOR = "operator"
    AGENT = "agent"


class Listing(BaseModel):
    listing_id: str
    title: str
    status: str = "active"
    price: float
    currency: str = "USD"
    stock: int = 0
    category: str | None = None
    content_quality: str | None = "good"
    attributes: dict[str, str] = Field(default_factory=dict)
    image_url: str | None = None
    short_description: str | None = None
    options: dict[str, list[str]] = Field(default_factory=dict)
    option_values: dict[str, str] = Field(default_factory=dict)
    variant_of: str | None = None

    @property
    def has_options(self) -> bool:
        return bool(self.options)


class ListingDetails(Listing):
    long_description: str | None = None
    review_snippets: list[str] = Field(default_factory=list)
    sales_last_30d: int | None = None
    return_rate_pct: float | None = None
    missing_attributes: list[str] = Field(default_factory=list)
    variants: list[Listing] = Field(default_factory=list)


class ChangeItem(BaseModel):
    target: str
    field: str
    before: Any = None
    after: Any = None


class StagedChange(BaseModel):
    change_id: str
    kind: ChangeKind
    status: ChangeStatus = ChangeStatus.STAGED
    summary: str = Field(max_length=200)
    items: list[ChangeItem] = Field(default_factory=list)
    created_at: datetime
    created_by: str
    created_by_kind: ActorKind = ActorKind.AGENT
    applied_at: datetime | None = None
    applied_by: str | None = None
    discarded_at: datetime | None = None
    discarded_by: str | None = None
    discarded_by_kind: ActorKind | None = None
    guardrail_notes: list[str] = Field(default_factory=list)
    currency: str | None = None
    margin_impact: float | None = None
    margin_before_pct: float | None = None
    margin_after_pct: float | None = None


class GuardrailViolation(ValueError):
    pass


class ChangeNotApplicable(ValueError):
    pass


class ChangeLedger:
    def __init__(self, max_items: int = 25) -> None:
        self.max_items = max_items
        self._changes: dict[str, StagedChange] = {}
        self._sequence = 0

    def stage(
        self,
        *,
        kind: ChangeKind,
        summary: str,
        items: list[ChangeItem],
        actor: str,
        currency: str | None = None,
        guardrail_notes: list[str] | None = None,
    ) -> StagedChange:
        self._check(kind, items)
        self._sequence += 1
        change = StagedChange(
            change_id=f"chg-{self._sequence:04d}",
            kind=kind,
            summary=summary[:200],
            items=items,
            created_at=datetime.now(UTC),
            created_by=actor,
            currency=currency,
            guardrail_notes=guardrail_notes or [],
        )
        self._changes[change.change_id] = change
        return change

    def get(self, change_id: str) -> StagedChange | None:
        return self._changes.get(change_id)

    def pending(self) -> list[StagedChange]:
        return [change for change in self._changes.values() if change.status is ChangeStatus.STAGED]

    def apply(self, change_id: str, actor: str) -> StagedChange:
        change = self._require_staged(change_id, "apply")
        self._check(change.kind, change.items)
        change = change.model_copy(
            update={
                "status": ChangeStatus.APPLIED,
                "applied_at": datetime.now(UTC),
                "applied_by": actor,
            }
        )
        self._changes[change_id] = change
        return change

    def discard(self, change_id: str, actor: str, actor_kind: ActorKind) -> StagedChange:
        change = self._require_staged(change_id, "discard")
        change = change.model_copy(
            update={
                "status": ChangeStatus.DISCARDED,
                "discarded_at": datetime.now(UTC),
                "discarded_by": actor,
                "discarded_by_kind": actor_kind,
            }
        )
        self._changes[change_id] = change
        return change

    def _require_staged(self, change_id: str, action: str) -> StagedChange:
        change = self._changes.get(change_id)
        if change is None:
            raise ChangeNotApplicable(f"No change with id {change_id!r} to {action}.")
        if change.status is not ChangeStatus.STAGED:
            raise ChangeNotApplicable(f"Change {change_id} is {change.status.value}, not staged.")
        return change

    def _check(self, kind: ChangeKind, items: list[ChangeItem]) -> None:
        if not items or len(items) > self.max_items:
            raise GuardrailViolation(f"A change must include 1-{self.max_items} items.")
        seen: set[tuple[str, str]] = set()
        for item in items:
            key = item.target, item.field.casefold()
            if key in seen:
                raise GuardrailViolation(f"{item.field} on {item.target} appears more than once.")
            seen.add(key)
            if item.field.casefold() in {
                "listing_id",
                "currency",
                "tax_category",
                "compliance_notes",
            }:
                raise GuardrailViolation(f"{item.field} is protected and cannot be changed.")
            if item.field == "price" or kind is ChangeKind.PROMOTION:
                try:
                    before, after = float(item.before), float(item.after)
                except (TypeError, ValueError) as error:
                    raise GuardrailViolation(
                        "Price changes require grounded positive prices."
                    ) from error
                if before <= 0 or after <= 0:
                    raise GuardrailViolation("Prices must be positive.")
                cap = 50 if kind is ChangeKind.PROMOTION else 20
                if abs(after - before) / before * 100 > cap:
                    raise GuardrailViolation(
                        f"Price change for {item.target} exceeds the {cap}% limit."
                    )
            if (
                kind is ChangeKind.INVENTORY_ACTION
                and item.field in {"stock", "rooms", "on_sale_capacity"}
                and int(item.after) - int(item.before) > 500
            ):
                raise GuardrailViolation("Restock exceeds the 500-unit per-change limit.")
            if (
                kind is ChangeKind.CAMPAIGN
                and item.field == "budget"
                and float(item.after) > 10_000
            ):
                raise GuardrailViolation("Campaign budget exceeds the 10000 per-change limit.")


def merchant_tools() -> tuple[ToolContract, ...]:
    return (
        _tool("get_business_snapshot", "Read current business performance and alerts.", {}),
        _tool(
            "query_metrics",
            "Read a metric time series.",
            {"metric": {"type": "string"}},
            ["metric"],
        ),
        _tool(
            "get_campaign_performance",
            "Read campaign performance.",
            {"campaign_id": {"type": "string"}},
        ),
        _tool(
            "search_listings",
            "Search merchant listings before staging a change.",
            {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            ["query"],
        ),
        _tool(
            "get_listing",
            "Read the complete listing record.",
            {"listing_id": {"type": "string"}},
            ["listing_id"],
        ),
        _tool("get_inventory_alerts", "Read low-stock and slow-mover alerts.", {}),
        _tool("get_order_issues", "Read open order issues.", {}),
        _tool(
            "get_pricing_context",
            "Read price, range, margin, and demand context.",
            {"listing_id": {"type": "string"}},
            ["listing_id"],
        ),
        _tool("get_pending_changes", "List staged changes awaiting approval.", {}),
        _tool(
            "stage_listing_update",
            "Stage listing content or attribute edits.",
            {
                "listing_id": {"type": "string"},
                "fields": {"type": "object"},
                "note": {"type": "string", "maxLength": 200},
            },
            ["listing_id", "fields"],
        ),
        _tool(
            "stage_price_update",
            "Stage permanent price changes using grounded listings.",
            {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "listing_id": {"type": "string"},
                            "new_price": {"type": "number", "exclusiveMinimum": 0},
                        },
                        "required": ["listing_id", "new_price"],
                        "additionalProperties": False,
                    },
                },
                "product_id": {"type": "string"},
                "new_price": {"type": "number", "exclusiveMinimum": 0},
                "note": {"type": "string", "maxLength": 200},
            },
        ),
        _tool(
            "stage_inventory_action",
            "Stage a restock, pause, or activation.",
            {"items": {"type": "array"}, "note": {"type": "string", "maxLength": 200}},
            ["items"],
        ),
        _tool(
            "stage_promotion",
            "Stage a date-bound promotion.",
            {
                "name": {"type": "string"},
                "listing_ids": {"type": "array", "items": {"type": "string"}},
                "discount_pct": {"type": "number", "minimum": -90, "maximum": 90},
                "starts": {"type": "string"},
                "ends": {"type": "string"},
            },
            ["name", "listing_ids", "discount_pct", "starts", "ends"],
        ),
        _tool(
            "stage_campaign",
            "Stage a new campaign or campaign update.",
            {
                "campaign_id": {"type": "string"},
                "name": {"type": "string"},
                "budget": {"type": "number", "minimum": 0},
                "objective": {"type": "string"},
                "audience": {"type": "string"},
                "copy_text": {"type": "string"},
            },
            ["name"],
        ),
        _tool(
            "apply_change",
            "Apply one host-approved staged change.",
            {"change_id": {"type": "string"}},
            ["change_id"],
        ),
        _tool(
            "discard_change",
            "Discard one staged change.",
            {"change_id": {"type": "string"}},
            ["change_id"],
        ),
    )


class MerchantExecutor:
    """Source-compatible merchant state machine over an in-memory catalog or source backend."""

    def __init__(
        self,
        products: list[Product] | None = None,
        operator: str = "demo-operator",
        backend: Any | None = None,
    ) -> None:
        self._operator = operator
        self._backend = backend
        self._products = {
            product.product_id: product.model_copy(deep=True) for product in products or []
        }
        self._ledger = ChangeLedger()
        self._approved: set[str] = set()
        self._seen_listings: set[str] = set()
        self._read_listings: set[str] = set()
        self._seen_changes: set[str] = set()
        self._campaigns: dict[str, dict[str, Any]] = {}

    def approve(self, change_id: str) -> StagedChange:
        change = self._ledger.get(change_id)
        if change is None or change.status is not ChangeStatus.STAGED:
            raise ChangeNotApplicable("Only a currently staged change can be approved.")
        self._approved.add(change_id)
        return change

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        try:
            if name == "get_business_snapshot":
                return self._fenced(
                    {
                        "period": arguments.get("period", "last_30_days"),
                        "sales": 0.0,
                        "orders": 0,
                        "alerts": {"pending_changes": len(self._ledger.pending())},
                        "note": "Metrics are unavailable in this fixture-backed merchant session.",
                    }
                )
            if name == "query_metrics":
                return self._fenced(
                    {
                        "metric": arguments["metric"],
                        "points": [],
                        "note": "Metric series unavailable in this fixture-backed merchant session.",
                    }
                )
            if name == "get_campaign_performance":
                campaigns = list(self._campaigns.values())
                if campaign_id := arguments.get("campaign_id"):
                    campaigns = [
                        campaign for campaign in campaigns if campaign["campaign_id"] == campaign_id
                    ]
                return self._fenced(campaigns or {"note": "No campaigns found."})
            if name == "search_listings":
                return self._search(arguments)
            if name == "get_listing":
                return self._listing_outcome(arguments["listing_id"])
            if name == "get_inventory_alerts":
                return self._fenced(self._inventory_alerts())
            if name == "get_order_issues":
                return self._fenced({"note": "No open order issues."})
            if name == "get_pricing_context":
                return self._pricing_outcome(arguments["listing_id"])
            if name == "get_pending_changes":
                pending = self._ledger.pending()
                self._seen_changes.update(change.change_id for change in pending)
                return self._fenced(
                    [change.model_dump(mode="json") for change in pending]
                    or {"note": "Nothing is waiting for approval."}
                )
            if name == "stage_listing_update":
                return self._stage_listing(arguments)
            if name == "stage_price_update":
                return self._stage_prices(arguments)
            if name == "stage_inventory_action":
                return self._stage_inventory(arguments)
            if name == "stage_promotion":
                return self._stage_promotion(arguments)
            if name == "stage_campaign":
                return self._stage_campaign(arguments)
            if name == "apply_change":
                return self._apply(arguments["change_id"])
            if name == "discard_change":
                return self._discard(arguments["change_id"])
        except (GuardrailViolation, ChangeNotApplicable, KeyError, ValueError) as error:
            return ToolOutcome(
                str(error),
                blocked="guardrail" if isinstance(error, GuardrailViolation) else None,
                is_error=not isinstance(error, GuardrailViolation),
            )
        return ToolOutcome(f"Unsupported merchant tool: {name}", is_error=True)

    def _catalog(self) -> dict[str, Any]:
        if self._backend is not None:
            return {
                **getattr(self._backend, "products", {}),
                **getattr(self._backend, "variants", {}),
            }
        return self._products

    def _listing(self, listing_id: str) -> Listing | None:
        product = self._catalog().get(listing_id)
        if product is None:
            return None
        stock = int(
            product.attributes.get("inventory", product.attributes.get("tickets_remaining", 40))
        )
        return Listing(
            listing_id=product.product_id,
            title=product.title,
            status="active" if product.in_stock else "out_of_stock",
            price=product.price,
            currency=getattr(product, "currency", "USD"),
            stock=stock,
            category=product.category,
            attributes=dict(product.attributes),
            image_url=getattr(product, "image_url", None),
            short_description=product.short_description,
            options=dict(product.options),
            option_values=dict(product.option_values),
            variant_of=product.variant_of,
        )

    def _search(self, arguments: dict[str, Any]) -> ToolOutcome:
        query = arguments["query"].casefold().strip()
        listings = [
            listing
            for product_id in self._catalog()
            if (listing := self._listing(product_id))
            and (not query or query in f"{listing.title} {listing.category}".casefold())
        ]
        listings = listings[: int(arguments.get("limit", 8))]
        self._seen_listings.update(listing.listing_id for listing in listings)
        return self._fenced(
            [listing.model_dump(mode="json") for listing in listings]
            or {"note": "No listings found."}
        )

    def _listing_outcome(self, listing_id: str) -> ToolOutcome:
        listing = self._listing(listing_id)
        if listing is None:
            return ToolOutcome(f"No listing with id {listing_id}.", is_error=True)
        product = self._catalog()[listing_id]
        variants = [
            self._listing(variant.product_id) for variant in getattr(product, "variants", [])
        ]
        details = ListingDetails(
            **listing.model_dump(),
            long_description=getattr(product, "long_description", None),
            review_snippets=list(getattr(product, "review_highlights", [])),
            variants=[variant for variant in variants if variant],
        )
        self._seen_listings.add(listing_id)
        self._read_listings.add(listing_id)
        self._seen_listings.update(variant.listing_id for variant in details.variants)
        return self._fenced(details.model_dump(mode="json"))

    def _pricing_outcome(self, listing_id: str) -> ToolOutcome:
        listing = self._listing(listing_id)
        if listing is None:
            return ToolOutcome(f"No pricing context for listing {listing_id}.", is_error=True)
        variants = [
            self._listing(variant.product_id)
            for variant in getattr(self._catalog()[listing_id], "variants", [])
        ]
        return self._fenced(
            {
                "listing_id": listing_id,
                "current_price": listing.price,
                "currency": listing.currency,
                "min_price": round(listing.price * 0.8, 2),
                "max_price": round(listing.price * 1.2, 2),
                "max_price_delta_pct": 20,
                "max_promotion_discount_pct": 50,
                "demand_signal": "steady",
                "variants": [variant.model_dump(mode="json") for variant in variants if variant],
            }
        )

    def _inventory_alerts(self) -> list[dict[str, Any]]:
        return [
            listing.model_dump(mode="json") | {"kind": "low_stock", "threshold": 8}
            for product_id in self._catalog()
            if (listing := self._listing(product_id))
            and not listing.has_options
            and listing.stock <= 8
        ]

    def _require_seen(self, ids: list[str], *, full: bool = False) -> None:
        known = self._read_listings if full else self._seen_listings
        missing = [listing_id for listing_id in ids if listing_id not in known]
        if missing:
            action = "get_listing" if full else "search_listings or get_listing"
            raise ChangeNotApplicable(
                f"Listing ids {', '.join(missing)} were not returned this session; call {action} first."
            )

    def _staged(self, change: StagedChange) -> ToolOutcome:
        self._seen_changes.add(change.change_id)
        payload = change.model_dump(mode="json")
        return ToolOutcome(
            MERCHANT_FENCE.fence_payload(
                {"staged": payload, "note": "Staged only; host approval is required before apply."}
            ),
            (AgentEvent("change_update", {"change": payload}),),
        )

    def _stage_listing(self, arguments: dict[str, Any]) -> ToolOutcome:
        listing_id, fields = arguments["listing_id"], arguments["fields"]
        self._require_seen([listing_id], full=True)
        if not fields:
            return ToolOutcome("No fields to change.", is_error=True)
        listing = self._listing(listing_id)
        assert listing
        items = [
            ChangeItem(
                target=listing_id,
                field=field,
                before=getattr(listing, field, listing.attributes.get(field)),
                after=value,
            )
            for field, value in fields.items()
        ]
        return self._staged(
            self._ledger.stage(
                kind=ChangeKind.LISTING_UPDATE,
                summary=arguments.get("note") or f"Update listing content on {listing_id}",
                items=items,
                actor=self._operator,
            )
        )

    def _stage_prices(self, arguments: dict[str, Any]) -> ToolOutcome:
        raw_items = arguments.get("items") or (
            [{"listing_id": arguments["product_id"], "new_price": arguments["new_price"]}]
            if "product_id" in arguments
            else []
        )
        if not raw_items:
            return ToolOutcome("No price changes to stage.", is_error=True)
        ids = [str(item["listing_id"]) for item in raw_items]
        if "items" in arguments:
            self._require_seen(ids)
        items: list[ChangeItem] = []
        for raw in raw_items:
            listing = self._listing(str(raw["listing_id"]))
            if listing is None:
                raise ChangeNotApplicable(f"No listing {raw['listing_id']}.")
            if listing.has_options:
                raise ChangeNotApplicable(
                    f"{listing.listing_id} has options and is priced per variant."
                )
            items.append(
                ChangeItem(
                    target=listing.listing_id,
                    field="price",
                    before=listing.price,
                    after=raw["new_price"],
                )
            )
        first_listing = self._listing(items[0].target)
        assert first_listing is not None
        currency = first_listing.currency
        return self._staged(
            self._ledger.stage(
                kind=ChangeKind.PRICE_UPDATE,
                summary=arguments.get("note") or f"Price update for {len(items)} listing(s)",
                items=items,
                actor=self._operator,
                currency=currency,
            )
        )

    def _stage_inventory(self, arguments: dict[str, Any]) -> ToolOutcome:
        raw_items = arguments["items"]
        self._require_seen([str(item["listing_id"]) for item in raw_items])
        items: list[ChangeItem] = []
        for raw in raw_items:
            listing = self._listing(str(raw["listing_id"]))
            if listing is None:
                raise ChangeNotApplicable(f"No listing {raw['listing_id']}.")
            action = raw["action"]
            if action == "restock":
                if listing.has_options:
                    raise ChangeNotApplicable(f"{listing.listing_id} is restocked per variant.")
                items.append(
                    ChangeItem(
                        target=listing.listing_id,
                        field="stock",
                        before=listing.stock,
                        after=listing.stock + int(raw.get("quantity") or 0),
                    )
                )
            else:
                items.append(
                    ChangeItem(
                        target=listing.listing_id,
                        field="status",
                        before=listing.status,
                        after="paused" if action == "pause" else "active",
                    )
                )
        return self._staged(
            self._ledger.stage(
                kind=ChangeKind.INVENTORY_ACTION,
                summary=arguments.get("note") or f"Inventory action for {len(items)} listing(s)",
                items=items,
                actor=self._operator,
            )
        )

    def _stage_promotion(self, arguments: dict[str, Any]) -> ToolOutcome:
        ids = [str(listing_id) for listing_id in arguments["listing_ids"]]
        self._require_seen(ids)
        discount = float(arguments["discount_pct"])
        if discount == 0:
            return ToolOutcome("A promotion needs a non-zero rate move.", is_error=True)
        items = []
        for listing_id in ids:
            listing = self._listing(listing_id)
            if listing is None:
                raise ChangeNotApplicable(f"No listing {listing_id}.")
            targets = (
                [listing]
                if not listing.has_options
                else [self._listing(v.product_id) for v in self._catalog()[listing_id].variants]
            )
            items.extend(
                ChangeItem(
                    target=target.listing_id,
                    field="promotion_price",
                    before=target.price,
                    after=round(target.price * (1 - discount / 100), 2),
                )
                for target in targets
                if target
            )
        return self._staged(
            self._ledger.stage(
                kind=ChangeKind.PROMOTION,
                summary=f"{arguments['name']} ({discount:.0f}% off, {arguments['starts']} to {arguments['ends']})",
                items=items,
                actor=self._operator,
            )
        )

    def _stage_campaign(self, arguments: dict[str, Any]) -> ToolOutcome:
        campaign_id = str(arguments.get("campaign_id") or f"campaign-{len(self._campaigns) + 1}")
        if arguments.get("campaign_id") and campaign_id not in self._campaigns:
            raise ChangeNotApplicable(
                "Campaign was not returned by get_campaign_performance this session."
            )
        before = self._campaigns.get(campaign_id, {})
        fields = {
            key: value
            for key, value in arguments.items()
            if key in {"name", "budget", "objective", "audience", "copy_text"} and value is not None
        }
        items = [
            ChangeItem(target=campaign_id, field=key, before=before.get(key), after=value)
            for key, value in fields.items()
        ]
        return self._staged(
            self._ledger.stage(
                kind=ChangeKind.CAMPAIGN,
                summary=f"Campaign: {arguments['name']}",
                items=items,
                actor=self._operator,
            )
        )

    def _apply(self, change_id: str) -> ToolOutcome:
        if change_id not in self._seen_changes:
            return ToolOutcome(
                "Change was not staged or listed in this session.", blocked="provenance"
            )
        if change_id not in self._approved:
            return ToolOutcome(
                "Host approval is required before applying this change.", blocked="host_approval"
            )
        self._approved.remove(change_id)
        change = self._ledger.apply(change_id, self._operator)
        for item in change.items:
            product = self._catalog().get(item.target)
            if change.kind is ChangeKind.CAMPAIGN:
                self._campaigns.setdefault(item.target, {"campaign_id": item.target})[
                    item.field
                ] = item.after
            elif product is not None:
                if item.field == "price":
                    product.price = float(item.after)
                elif item.field == "status":
                    product.in_stock = item.after == "active"
                elif item.field == "stock":
                    product.attributes["inventory"] = str(item.after)
                elif item.field not in {"promotion_price"}:
                    setattr(product, item.field, item.after) if hasattr(
                        product, item.field
                    ) else product.attributes.__setitem__(item.field, str(item.after))
        return self._change_outcome(change)

    def _discard(self, change_id: str) -> ToolOutcome:
        if change_id not in self._seen_changes:
            return ToolOutcome(
                "Change was not staged or listed in this session.", blocked="provenance"
            )
        self._approved.discard(change_id)
        return self._change_outcome(
            self._ledger.discard(change_id, self._operator, ActorKind.AGENT)
        )

    @staticmethod
    def _fenced(payload: Any) -> ToolOutcome:
        return ToolOutcome(MERCHANT_FENCE.fence_payload(payload))

    @staticmethod
    def _change_outcome(change: StagedChange) -> ToolOutcome:
        payload = change.model_dump(mode="json")
        return ToolOutcome(
            MERCHANT_FENCE.fence_payload(payload),
            (AgentEvent("change_update", {"change": payload}),),
        )


def _tool(
    name: str, description: str, properties: dict[str, Any], required: list[str] | None = None
) -> ToolContract:
    return ToolContract(
        name,
        description,
        {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    )

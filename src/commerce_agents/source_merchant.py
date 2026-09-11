"""PydanticAI executor over the vendored source merchant backends."""

from __future__ import annotations

from typing import Any

from .events import AgentEvent, ToolOutcome
from .fencing import Fence
from .reference.merchant_agent import (
    ActorKind,
    CampaignDraft,
    ChangeNotApplicable,
    GuardrailViolation,
    InventoryActionItem,
    MerchantSessionContext,
    MerchantSessionState,
    PriceUpdateItem,
    PromotionDraft,
)

_FENCE = Fence("merchant_data")


class SourceMerchantExecutor:
    """Keeps source backend writes behind the existing host-owned approval control."""

    def __init__(self, backend: Any, session_id: str, operator: str = "demo-operator") -> None:
        self._backend = backend
        self._session = MerchantSessionContext(
            session_id=session_id,
            merchant_id=getattr(backend, "merchant_id", "demo-merchant"),
            operator=operator,
        )
        self._state = MerchantSessionState()

    def approve(self, change_id: str) -> Any:
        change = self._state.seen_changes.get(change_id)
        if change is None:
            raise ChangeNotApplicable(
                "Only a staged change returned in this session can be approved."
            )
        self._state.approved_change_ids.add(change_id)
        return change

    async def change_action(
        self, change_id: str, action: str
    ) -> tuple[bool, Any | None, str | None]:
        """Run a portal preview-card action through the same approval gate as the agent."""
        if action == "apply_change":
            self._state.approved_change_ids.add(change_id)
        try:
            outcome = await self.execute(action, {"change_id": change_id})
        finally:
            self._state.approved_change_ids.discard(change_id)
        if outcome.is_error:
            raise ValueError(outcome.result_text)
        if outcome.blocked:
            return False, None, outcome.result_text
        change = next(
            (event.data.get("change") for event in outcome.events if event.type == "change_update"),
            None,
        )
        return True, change, None

    @property
    def backend(self) -> Any:
        return self._backend

    @property
    def session(self) -> MerchantSessionContext:
        return self._session

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        try:
            if name == "get_business_snapshot":
                snapshot = await self._backend.get_business_snapshot(
                    self._session, arguments.get("period")
                )
                self._state.remember_snapshot(snapshot)
                return self._fenced(snapshot)
            if name == "query_metrics":
                series = await self._backend.query_metrics(
                    self._session,
                    arguments["metric"],
                    arguments.get("period"),
                    arguments.get("granularity", "day"),
                    arguments.get("segment"),
                )
                self._state.remember_series(series)
                return self._fenced(series)
            if name == "get_campaign_performance":
                campaigns = await self._backend.get_campaign_performance(
                    self._session, arguments.get("campaign_id")
                )
                self._state.remember_campaigns(campaigns)
                return self._fenced(campaigns or {"note": "No campaigns found."})
            if name == "search_listings":
                listings = await self._backend.search_listings(
                    self._session, arguments["query"], None, arguments.get("limit", 8)
                )
                self._state.remember_listings(listings)
                return self._fenced(listings or {"note": "No listings found."})
            if name == "get_listing":
                listing = await self._backend.get_listing(self._session, arguments["listing_id"])
                if listing is None:
                    return ToolOutcome("Listing not found.", is_error=True)
                self._state.remember_listing_record(listing)
                return self._fenced(listing)
            if name == "get_inventory_alerts":
                return self._fenced(await self._backend.get_inventory_alerts(self._session))
            if name == "get_order_issues":
                return self._fenced(await self._backend.get_order_issues(self._session))
            if name == "get_pricing_context":
                context = await self._backend.get_pricing_context(
                    self._session, arguments["listing_id"]
                )
                return (
                    self._fenced(context)
                    if context
                    else ToolOutcome("Pricing context not found.", is_error=True)
                )
            if name == "get_pending_changes":
                changes = await self._backend.get_pending_changes(self._session)
                for change in changes:
                    self._state.remember_change(change)
                return self._fenced(changes or {"note": "Nothing is waiting for approval."})
            if name == "stage_listing_update":
                self._require_listing(arguments["listing_id"], full=True)
                change = await self._backend.stage_listing_update(
                    self._session,
                    arguments["listing_id"],
                    arguments["fields"],
                    arguments.get("note"),
                )
            elif name == "stage_price_update":
                items = [PriceUpdateItem.model_validate(item) for item in arguments["items"]]
                self._require_listings([item.listing_id for item in items])
                change = await self._backend.stage_price_update(
                    self._session, items, arguments.get("note")
                )
            elif name == "stage_inventory_action":
                items = [InventoryActionItem.model_validate(item) for item in arguments["items"]]
                self._require_listings([item.listing_id for item in items])
                change = await self._backend.stage_inventory_action(
                    self._session, items, arguments.get("note")
                )
            elif name == "stage_promotion":
                draft = PromotionDraft.model_validate(arguments)
                self._require_listings(draft.listing_ids)
                change = await self._backend.stage_promotion(self._session, draft)
            elif name == "stage_campaign":
                draft = CampaignDraft.model_validate(arguments)
                if draft.campaign_id and draft.campaign_id not in self._state.seen_campaigns:
                    raise ChangeNotApplicable(
                        "Read campaign performance before changing a campaign."
                    )
                change = await self._backend.stage_campaign(self._session, draft)
            elif name == "apply_change":
                change_id = arguments["change_id"]
                if change_id not in self._state.approved_change_ids:
                    return ToolOutcome(
                        "Host approval is required before applying this change.",
                        blocked="host_approval",
                    )
                self._state.approved_change_ids.remove(change_id)
                change = await self._backend.apply_change(self._session, change_id)
            elif name == "discard_change":
                change = await self._backend.discard_change(
                    self._session, arguments["change_id"], ActorKind.AGENT
                )
            else:
                return ToolOutcome(f"Unsupported merchant tool: {name}", is_error=True)
        except GuardrailViolation as error:
            return ToolOutcome(str(error), blocked="guardrail")
        except (ChangeNotApplicable, KeyError, ValueError) as error:
            return ToolOutcome(str(error), is_error=True)
        self._state.remember_change(change)
        payload = change.model_dump(mode="json")
        return ToolOutcome(
            _FENCE.fence_payload(payload), (AgentEvent("change_update", {"change": payload}),)
        )

    def _require_listing(self, listing_id: str, *, full: bool = False) -> None:
        known = self._state.read_listings if full else self._state.seen_listings
        if listing_id not in known:
            raise ChangeNotApplicable("Read the listing in this session before staging a change.")

    def _require_listings(self, listing_ids: list[str]) -> None:
        for listing_id in listing_ids:
            self._require_listing(listing_id)

    @staticmethod
    def _fenced(payload: Any) -> ToolOutcome:
        return ToolOutcome(
            _FENCE.fence_payload(
                payload.model_dump(mode="json")
                if hasattr(payload, "model_dump")
                else [item.model_dump(mode="json") for item in payload]
                if isinstance(payload, list)
                else payload
            )
        )

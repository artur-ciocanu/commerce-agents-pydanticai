"""Merchant staged-change lifecycle with host-owned approval grants."""

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
    PRICE_UPDATE = "price_update"


class ChangeStatus(StrEnum):
    STAGED = "staged"
    APPLIED = "applied"
    DISCARDED = "discarded"


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
    items: list[ChangeItem]
    created_at: datetime
    created_by: str
    applied_at: datetime | None = None
    applied_by: str | None = None
    discarded_at: datetime | None = None
    discarded_by: str | None = None
    guardrail_notes: list[str] = Field(default_factory=list)


class GuardrailViolation(ValueError):
    pass


class ChangeNotApplicable(ValueError):
    pass


class ChangeLedger:
    def __init__(self, *, max_price_delta_pct: float = 20.0, max_items: int = 10) -> None:
        self._max_price_delta_pct = max_price_delta_pct
        self._max_items = max_items
        self._changes: dict[str, StagedChange] = {}
        self._sequence = 0

    def stage(self, *, summary: str, items: list[ChangeItem], actor: str) -> StagedChange:
        self._check(items)
        self._sequence += 1
        change = StagedChange(
            change_id=f"chg-{self._sequence:04d}",
            kind=ChangeKind.PRICE_UPDATE,
            summary=summary[:200],
            items=items,
            created_at=datetime.now(UTC),
            created_by=actor,
        )
        self._changes[change.change_id] = change
        return change

    def pending(self) -> list[StagedChange]:
        return [change for change in self._changes.values() if change.status is ChangeStatus.STAGED]

    def get(self, change_id: str) -> StagedChange | None:
        return self._changes.get(change_id)

    def apply(self, change_id: str, actor: str) -> StagedChange:
        change = self._require_staged(change_id, "apply")
        self._check(change.items)
        applied = change.model_copy(
            update={
                "status": ChangeStatus.APPLIED,
                "applied_at": datetime.now(UTC),
                "applied_by": actor,
            }
        )
        self._changes[change_id] = applied
        return applied

    def discard(self, change_id: str, actor: str) -> StagedChange:
        change = self._require_staged(change_id, "discard")
        discarded = change.model_copy(
            update={
                "status": ChangeStatus.DISCARDED,
                "discarded_at": datetime.now(UTC),
                "discarded_by": actor,
            }
        )
        self._changes[change_id] = discarded
        return discarded

    def _require_staged(self, change_id: str, action: str) -> StagedChange:
        change = self._changes.get(change_id)
        if change is None:
            raise ChangeNotApplicable(f"No change with id {change_id!r} to {action}.")
        if change.status is not ChangeStatus.STAGED:
            raise ChangeNotApplicable(f"Change {change_id} is {change.status}, not staged.")
        return change

    def _check(self, items: list[ChangeItem]) -> None:
        if not items or len(items) > self._max_items:
            raise GuardrailViolation(f"A change must include 1-{self._max_items} items.")
        seen: set[tuple[str, str]] = set()
        for item in items:
            key = (item.target, item.field)
            if key in seen:
                raise GuardrailViolation(f"{item.field} on {item.target} appears more than once.")
            seen.add(key)
            if item.field != "price":
                raise GuardrailViolation(
                    f"{item.field} is protected; only price changes are supported."
                )
            try:
                before, after = float(item.before), float(item.after)
            except (TypeError, ValueError) as error:
                raise GuardrailViolation(
                    "Price changes require grounded positive prices."
                ) from error
            if before <= 0 or after <= 0:
                raise GuardrailViolation("Prices must be positive.")
            if abs(after - before) / before * 100 > self._max_price_delta_pct:
                raise GuardrailViolation(
                    f"Price change for {item.target} exceeds the {self._max_price_delta_pct:.0f}% limit."
                )


def merchant_tools() -> tuple[ToolContract, ...]:
    return (
        ToolContract(
            "get_business_snapshot", "Read current retail performance and inventory.", _schema({})
        ),
        ToolContract(
            "get_listing",
            "Read a listing before proposing a price change.",
            _schema({"product_id": {"type": "string"}}, ["product_id"]),
        ),
        ToolContract(
            "run_analysis",
            "Ask a read-only specialist to analyze the current business snapshot.",
            _schema({"question": {"type": "string", "maxLength": 300}}, ["question"]),
        ),
        ToolContract(
            "stage_price_update",
            "Stage a bounded price change for host approval.",
            _schema(
                {
                    "product_id": {"type": "string"},
                    "new_price": {"type": "number", "exclusiveMinimum": 0},
                    "note": {"type": "string", "maxLength": 200},
                },
                ["product_id", "new_price"],
            ),
        ),
        ToolContract("get_pending_changes", "List staged changes awaiting approval.", _schema({})),
        ToolContract(
            "apply_change",
            "Apply a host-approved staged change exactly once.",
            _schema({"change_id": {"type": "string"}}, ["change_id"]),
        ),
        ToolContract(
            "discard_change",
            "Discard a staged change.",
            _schema({"change_id": {"type": "string"}}, ["change_id"]),
        ),
    )


class MerchantExecutor:
    def __init__(self, products: list[Product], operator: str = "demo-operator") -> None:
        self._products = {product.product_id: product.model_copy(deep=True) for product in products}
        self._operator = operator
        self._ledger = ChangeLedger()
        self._approved: set[str] = set()

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
                    {"revenue_last_30_days": 18420, "orders": 96, "low_inventory": ["TR-200"]}
                )
            if name == "get_listing":
                product = self._products.get(arguments["product_id"])
                return (
                    self._fenced(product.model_dump())
                    if product
                    else ToolOutcome("Listing not found.", is_error=True)
                )
            if name == "stage_price_update":
                return self._stage(arguments)
            if name == "get_pending_changes":
                return self._fenced(
                    [change.model_dump(mode="json") for change in self._ledger.pending()]
                )
            if name == "apply_change":
                return self._apply(arguments["change_id"])
            if name == "discard_change":
                self._approved.discard(arguments["change_id"])
                return self._change_outcome(
                    self._ledger.discard(arguments["change_id"], self._operator)
                )
        except (GuardrailViolation, ChangeNotApplicable) as error:
            return ToolOutcome(
                str(error),
                blocked="guardrail" if isinstance(error, GuardrailViolation) else None,
                is_error=not isinstance(error, GuardrailViolation),
            )
        return ToolOutcome(f"Unsupported merchant tool: {name}", is_error=True)

    def _stage(self, arguments: dict[str, Any]) -> ToolOutcome:
        product = self._products.get(arguments["product_id"])
        if product is None:
            return ToolOutcome("Listing not found.", is_error=True)
        change = self._ledger.stage(
            summary=arguments.get("note") or f"Update {product.title} price",
            items=[
                ChangeItem(
                    target=product.product_id,
                    field="price",
                    before=product.price,
                    after=arguments["new_price"],
                )
            ],
            actor=self._operator,
        )
        return self._change_outcome(change)

    def _apply(self, change_id: str) -> ToolOutcome:
        if change_id not in self._approved:
            return ToolOutcome(
                "Host approval is required before applying this change.", blocked="host_approval"
            )
        self._approved.remove(change_id)
        change = self._ledger.apply(change_id, self._operator)
        for item in change.items:
            product = self._products[item.target]
            self._products[item.target] = product.model_copy(update={"price": float(item.after)})
        return self._change_outcome(change)

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


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }

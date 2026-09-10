"""Provider-agnostic commerce agent primitives backed by PydanticAI."""

from .events import AgentEvent, ToolOutcome
from .fencing import Fence
from .merchant import ChangeLedger, MerchantExecutor, StagedChange
from .runtime import CommerceAgent, CommerceDependencies, ToolContract, ToolExecutor
from .shopping import ShoppingExecutor, ShoppingSessionState, StorefrontBackend
from .skills import Skill, SkillRegistry

__all__ = [
    "AgentEvent",
    "ChangeLedger",
    "CommerceAgent",
    "CommerceDependencies",
    "Fence",
    "MerchantExecutor",
    "ShoppingExecutor",
    "ShoppingSessionState",
    "Skill",
    "SkillRegistry",
    "StagedChange",
    "StorefrontBackend",
    "ToolContract",
    "ToolExecutor",
    "ToolOutcome",
]

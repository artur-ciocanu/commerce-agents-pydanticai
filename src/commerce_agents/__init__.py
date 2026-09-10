"""Provider-agnostic commerce agent primitives backed by PydanticAI."""

from .analysis import MerchantAnalysis
from .events import AgentEvent, ToolOutcome
from .fencing import Fence
from .memory import MemoryWriteRejected, SessionMemory
from .merchant import ChangeLedger, MerchantExecutor, StagedChange
from .runtime import (
    AnalysisDelegate,
    CommerceAgent,
    CommerceDependencies,
    ToolContract,
    ToolExecutor,
)
from .shopping import ShoppingExecutor, ShoppingSessionState, StorefrontBackend
from .skills import Skill, SkillRegistry
from .travel import TravelBackend

__all__ = [
    "AgentEvent",
    "AnalysisDelegate",
    "ChangeLedger",
    "CommerceAgent",
    "CommerceDependencies",
    "Fence",
    "MemoryWriteRejected",
    "MerchantAnalysis",
    "MerchantExecutor",
    "SessionMemory",
    "ShoppingExecutor",
    "ShoppingSessionState",
    "Skill",
    "SkillRegistry",
    "StagedChange",
    "StorefrontBackend",
    "ToolContract",
    "ToolExecutor",
    "ToolOutcome",
    "TravelBackend",
]

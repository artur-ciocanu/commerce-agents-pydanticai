from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from commerce_agents import MerchantAnalysis, ToolOutcome


class SnapshotExecutor:
    async def execute(self, name: str, arguments: dict) -> ToolOutcome:
        assert name == "get_business_snapshot"
        assert arguments == {}
        return ToolOutcome('<merchant_data>{"orders": 96}</merchant_data>')


async def test_analysis_delegate_only_reads_the_business_snapshot() -> None:
    analysis = MerchantAnalysis("test")

    def model(messages, _: AgentInfo) -> ModelResponse:
        prompt = str(messages)
        assert "orders" in prompt
        assert "Which metric changed?" in prompt
        return ModelResponse(parts=[TextPart("Orders are the available metric.")])

    with analysis._agent.override(model=FunctionModel(model)):
        outcome = await analysis.run(SnapshotExecutor(), {"question": "Which metric changed?"})

    assert outcome.result_text == "Orders are the available metric."

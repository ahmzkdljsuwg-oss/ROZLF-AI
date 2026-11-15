import pytest

from ai.review import AIReviewer, parse_verdict


class FakeAI:
    configured = True

    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    async def analyse_setup(self, payload):
        self.calls.append(payload)
        if self.error:
            raise self.error
        return self.reply


def test_parse_verdict_json():
    verdict = parse_verdict("Gemini", '{"decision":"UP","confidence":81,"reason":"EMA + RSI"}')
    assert verdict.decision == "UP"
    assert verdict.confidence == 81.0


def test_parse_verdict_plain_and_clamps():
    verdict = parse_verdict("Mistral", "I choose DOWN with confidence 140")
    assert verdict.decision == "DOWN"
    assert verdict.confidence is None


def test_parse_verdict_rejects_garbage():
    assert parse_verdict("Gemini", "I cannot answer") is None


@pytest.mark.asyncio
async def test_review_confirms_when_models_agree():
    gemini = FakeAI('{"decision":"UP","confidence":70,"reason":"trend"}')
    mistral = FakeAI('{"decision":"UP","confidence":66,"reason":"momentum"}')
    outcome = await AIReviewer(gemini, mistral).review("UP", {"price": 1.1})
    assert outcome.confirmed
    assert outcome.conflict is None
    assert {v.model for v in outcome.verdicts} == {"Gemini", "Mistral"}
    assert gemini.calls and mistral.calls


@pytest.mark.asyncio
async def test_review_blocks_on_disagreement():
    reviewer = AIReviewer(FakeAI('{"decision":"DOWN","confidence":60}'), FakeAI('{"decision":"UP"}'))
    outcome = await reviewer.review("UP", {})
    assert not outcome.confirmed
    assert "DOWN" in outcome.conflict


@pytest.mark.asyncio
async def test_review_ignores_unavailable_model_without_inventing():
    reviewer = AIReviewer(FakeAI(error=RuntimeError("down")), FakeAI('{"decision":"UP"}'))
    outcome = await reviewer.review("UP", {})
    assert outcome.confirmed
    assert outcome.unavailable == ["Gemini"]


@pytest.mark.asyncio
async def test_unconfigured_models_are_not_called():
    outcome = await AIReviewer(None, None).review("UP", {})
    assert outcome.verdicts == []
    assert outcome.conflict is None

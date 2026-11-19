from datetime import timedelta

import engines.technical.analyzer as analyzer
import engines.technical.next_candle as next_candle
from engines.technical.analyzer import analyze_market_data
from engines.technical.indicators import frame_from_candles
from tests.conftest import make_candles
from tests.test_evidence_engine import _market
from providers.base import Candle, utc_now
from providers.catalog import Market, assets_for


def test_analyzer_never_passes_a_forming_candle_to_forecast(monkeypatch):
    now = utc_now()
    closed = make_candles(260, tf_seconds=60, end=now - timedelta(seconds=60))
    forming_open = closed[-1].time + timedelta(seconds=60)
    forming = Candle(
        forming_open,
        closed[-1].close,
        closed[-1].close * 1.02,
        closed[-1].close * 0.98,
        closed[-1].close * 1.01,
    )
    data = _market(assets_for(Market.GOLD)[0], closed + [forming], tf="1min")
    seen = {}

    def capture(frame, **kwargs):
        seen["last_time"] = frame.index[-1].to_pydatetime()
        seen["target"] = kwargs["target_open_at"]
        seen["horizon_bars"] = kwargs["horizon_bars"]
        return next_candle.NextCandleForecast(
            "NO TRADE", 0, None, None, [], {}, kwargs["target_open_at"], 60,
            "test", ["test"],
        )

    monkeypatch.setattr(analyzer, "forecast_from_frame", capture)
    analyze_market_data(data, now=now)

    assert seen["last_time"] == closed[-1].time
    assert seen["last_time"] < forming.time
    assert seen["horizon_bars"] == 2
    assert seen["target"] == forming.time + timedelta(seconds=60)


def test_confidence_requires_matching_calibration_lead_and_expiry():
    frame = frame_from_candles(
        make_candles(240, tf_seconds=60, end=utc_now() - timedelta(seconds=60))
    )
    now = frame.index[-1].to_pydatetime() + timedelta(seconds=60)
    bins = [{"low": 0, "high": 100, "n": 100, "up_wins": 60, "draws": 0}]
    cal = {"markets": {"gold": {"1min": {
        "enabled": True, "horizon_bars": 1, "expiry_seconds": 60,
        "bins": bins,
    }}}}

    lead_mismatch = next_candle.forecast_from_frame(
        frame, market="gold", timeframe_code="1min", timeframe_seconds=60,
        now=now, target_open_at=now, horizon_bars=2, expiry_seconds=60,
        calibration=cal,
    )
    expiry_mismatch = next_candle.forecast_from_frame(
        frame, market="gold", timeframe_code="1min", timeframe_seconds=60,
        now=now, target_open_at=now, horizon_bars=1, expiry_seconds=300,
        calibration=cal,
    )

    assert lead_mismatch.direction == "NO TRADE"
    assert lead_mismatch.confidence is None
    assert "horizon mismatch" in lead_mismatch.blockers[0]
    assert expiry_mismatch.direction == "NO TRADE"
    assert expiry_mismatch.confidence is None
    assert "expiry mismatch" in expiry_mismatch.blockers[0]


def test_prediction_at_exact_next_open_is_time_valid():
    frame = frame_from_candles(
        make_candles(240, tf_seconds=60, end=utc_now() - timedelta(seconds=60))
    )
    target = frame.index[-1].to_pydatetime() + timedelta(seconds=60)
    result = next_candle.forecast_from_frame(
        frame, market="gold", timeframe_code="1min", timeframe_seconds=60,
        now=target, target_open_at=target, require_calibration=False,
    )
    assert not any("already opened" in blocker for blocker in result.blockers)


def test_legacy_calibration_flags_do_not_count_as_verified_frames():
    legacy = {"markets": {"forex": {"1min": {"enabled": True, "bins": []}}}}
    verified = {"markets": {"forex": {"1min": {"horizons": {
        "1": {"enabled": True, "horizon_bars": 1, "expiry_seconds": 60,
              "wilson_95_lower_hit_rate": 57.0, "break_even_hit_rate": 55.56,
              "bins": [{"low": 0, "high": 10, "n": 50}]},
    }}}}}

    assert next_candle.enabled_frames("forex", legacy) == []
    assert next_candle.enabled_frames("forex", verified) == ["1min"]


def test_selected_score_bucket_must_clear_its_own_payout_gate(monkeypatch):
    frame = frame_from_candles(
        make_candles(240, tf_seconds=60, end=utc_now() - timedelta(seconds=60))
    )
    target = frame.index[-1].to_pydatetime() + timedelta(seconds=60)
    monkeypatch.setattr(next_candle, "score_at", lambda *_args: (10.0, {"trend": 10.0}))

    def calibration(up_wins):
        bins = [{
            "low": 8, "high": 12, "n": 40, "up_wins": up_wins, "down_wins": 40 - up_wins,
            "draws": 0, "predicted_up_n": 40, "predicted_up_wins": up_wins,
            "predicted_down_n": 0, "predicted_down_wins": 0,
        }]
        return {"markets": {"gold": {"1min": {
            "horizons": {"1": {
                "enabled": True, "horizon_bars": 1, "expiry_seconds": 60,
                "wilson_95_lower_hit_rate": 60.0,
                "break_even_hit_rate": 55.56,
                "bins": bins,
            }},
        }}}}

    weak = next_candle.forecast_from_frame(
        frame, market="gold", timeframe_code="1min", timeframe_seconds=60,
        now=target, target_open_at=target, expiry_seconds=60,
        calibration=calibration(24),
    )
    strong = next_candle.forecast_from_frame(
        frame, market="gold", timeframe_code="1min", timeframe_seconds=60,
        now=target, target_open_at=target, expiry_seconds=60,
        calibration=calibration(38),
    )

    assert weak.direction == "NO TRADE"
    assert "score bucket 95% lower bound" in weak.blockers[0]
    assert strong.direction == "UP"
    assert strong.confidence == 95.0

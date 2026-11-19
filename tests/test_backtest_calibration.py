from datetime import datetime, timedelta, timezone

from scripts.backtest_next_candle import _history_matches, _wilson_lower_bound, _walk_forward


def test_history_ingestion_rejects_wrong_or_inactive_markets():
    valid = {
        "asset_id": 142, "market": "forex", "symbol": "EURUSD",
        "timeframe": "60s", "active": True, "connected": True,
    }
    assert _history_matches(valid, 142, "1min")
    assert not _history_matches({**valid, "market": "otc"}, 142, "1min")
    assert not _history_matches({**valid, "active": False}, 142, "1min")
    assert not _history_matches({**valid, "timeframe": "300s"}, 142, "1min")


def test_break_even_gate_accounts_for_payout_and_sampling_uncertainty():
    lower = _wilson_lower_bound(178, 332)
    binary_option_break_even = 1 / (1 + 0.80)
    assert lower < binary_option_break_even


def test_walk_forward_does_not_train_on_a_peer_at_the_same_timestamp():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        {"time": (start + timedelta(minutes=index)).isoformat(), "score": 10.0,
         "abs_score": 10.0, "target": "UP"}
        for index in range(299)
    ]
    rows.extend([
        {"time": (start + timedelta(minutes=299)).isoformat(), "score": 10.0,
         "abs_score": 10.0, "target": "UP"},
        {"time": (start + timedelta(minutes=299)).isoformat(), "score": 10.0,
         "abs_score": 10.0, "target": "DOWN"},
    ])

    _, tested = _walk_forward(rows)

    assert [row["prediction"] for row in tested[-2:]] == ["NO TRADE", "NO TRADE"]


def test_walk_forward_purges_unsettled_target_rows():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(300):
        feature_time = start + timedelta(minutes=index)
        rows.append({
            "time": feature_time.isoformat(),
            "decision_time": feature_time.isoformat(),
            "target_time": (feature_time + timedelta(minutes=2)).isoformat(),
            "score": 10.0, "abs_score": 10.0, "target": "UP",
        })
    current = start + timedelta(minutes=300)
    rows.append({
        "time": current.isoformat(), "decision_time": current.isoformat(),
        "target_time": (current + timedelta(minutes=2)).isoformat(),
        "score": 10.0, "abs_score": 10.0, "target": "DOWN",
    })

    _, tested = _walk_forward(rows)

    assert tested[-1]["prediction"] == "NO TRADE"

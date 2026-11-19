import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "simulator"))
import aurasense_sim as sim  # noqa: E402


@pytest.fixture(scope="module")
def week():
    end = datetime(2026, 11, 20, tzinfo=timezone.utc)
    return list(sim.generate(end - timedelta(days=7), end, 60, sim.Room(seed=1), "mixed", 1))


def test_deterministic_for_a_seed():
    end = datetime(2026, 11, 20, tzinfo=timezone.utc)
    run = lambda: list(sim.generate(end - timedelta(hours=6), end, 60, sim.Room(seed=3), "normal", 3))  # noqa: E731
    assert run() == run()


def test_readings_are_physically_plausible(week):
    for _, r in week:
        assert 400 <= r["eco2"] < 5000
        assert 0 <= r["tvoc"] < 3000
        assert 15 <= r["temperature"] <= 26
        assert 10 <= r["humidity"] <= 95
        assert 940 < r["pressure"] < 990


def test_co2_follows_occupancy(week):
    def median_eco2(pred):
        vals = sorted(r["eco2"] for ts, r in week if pred(ts.astimezone(sim.LOCAL_TZ)))
        return vals[len(vals) // 2]
    night = median_eco2(lambda t: 2 <= t.hour < 6)
    empty_weekday = median_eco2(lambda t: t.weekday() < 5 and 13 <= t.hour < 17)
    assert night > 900 and empty_weekday < 550


def test_no_motion_when_nobody_is_home(week):
    away = [r["motion"] for ts, r in week
            if (t := ts.astimezone(sim.LOCAL_TZ)).weekday() < 5 and 9 <= t.hour < 17]
    assert away and not any(away)


def test_stuffy_scenario_reaches_danger_and_normal_mostly_does_not():
    end = datetime(2026, 11, 20, tzinfo=timezone.utc)
    peak = {name: max(r["eco2"] for _, r in sim.generate(end - timedelta(days=3), end, 60,
                                                          sim.Room(seed=2), name, 2))
            for name in ("normal", "stuffy")}
    assert peak["stuffy"] > 1500 > peak["normal"] - 300


def test_dry_scenario_is_dry():
    end = datetime(2026, 11, 20, tzinfo=timezone.utc)
    hums = [r["humidity"] for _, r in sim.generate(end - timedelta(days=2), end, 60, sim.Room(seed=4), "dry", 4)]
    assert sorted(hums)[len(hums) // 2] < 32


def test_mixed_scenario_distribution():
    days = [datetime(2026, 1, 1) + timedelta(days=i) for i in range(1000)]
    counts = Counter(sim.scenario_for(d, "mixed", 42).name for d in days)
    assert 600 < counts["normal"] < 800 and 100 < counts["stuffy"] < 200 and 80 < counts["dry"] < 220


def test_eco2_is_biased_by_voc():
    room = sim.Room(seed=5)
    room.co2, room.voc = 800.0, 0.0
    clean = sum(room.reading(datetime.now(sim.LOCAL_TZ))["eco2"] for _ in range(200)) / 200
    room.voc = 400.0
    polluted = sum(room.reading(datetime.now(sim.LOCAL_TZ))["eco2"] for _ in range(200)) / 200
    assert 280 < polluted - clean < 360                     # 0.8 ppm per ppb of extra VOC


def test_export_cli(tmp_path):
    out = tmp_path / "r.csv"
    sim.main(["export", "--days", "1", "--out", str(out)])
    lines = out.read_text().splitlines()
    assert lines[0] == "timestamp,temperature,humidity,pressure,eco2,tvoc,motion" and len(lines) == 1441

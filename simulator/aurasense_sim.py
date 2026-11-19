#!/usr/bin/env python3
"""
aurasense_sim.py — Virtual AuraSense device for demos and testing.
"AuraSense: See the air you breathe."

Generates physically plausible indoor-air readings and sends them to the
backend exactly like the M5Stack Core2 does, so the whole system can run
without hardware. Standard library only.

Model (one room, explicit Euler integration)
-------------------------------------------
CO2 mass balance
    dC/dt = G·10⁶ / V  −  ACH · (C − C_out)
    G   CO2 generation, m³/h (≈0.019 per awake adult, ≈0.013 asleep)
    V   room volume, m³;  ACH  air changes per hour (window open → ~6/h)
Occupants follow a weekday / weekend schedule and, in the "normal" scenario,
tend to open a window when the air gets stuffy.

TVOC   cooking and occupancy act as sources; removed by the same ventilation.
eCO2   The SGP30 does not measure CO2: it estimates "eCO2" from H₂/VOC
       signals. The reported value therefore tracks true CO2 but is biased
       upward by VOC events, plus sensor noise.
Temp   relaxes to a heating set-point (lower at night); open windows cool.
RH     relaxes to a scenario baseline; people, cooking and showers add moisture.
Motion PIR triggers with high probability when someone is awake at home.

Scenarios: normal · stuffy (nobody ventilates) · dry (winter heating) ·
mixed (a deterministic mix of the three, one per day; the default)

Usage
-----
    python aurasense_sim.py run      # backfill history, then stream live
    python aurasense_sim.py backfill --days 7
    python aurasense_sim.py live --interval 10
    python aurasense_sim.py export --days 7 --out readings.csv   # no backend

Environment: AURASENSE_URL, AURASENSE_API_KEY, SIM_DEVICE_ID, SIM_SCENARIO
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Zurich")

# ── Physical constants ────────────────────────────────────────────────────────
CO2_OUTDOOR      = 420.0     # ppm
GEN_AWAKE        = 0.019     # m³/h CO2 per adult, light activity
GEN_ASLEEP       = 0.013     # m³/h CO2 per adult, sleeping
ACH_WINDOW_OPEN  = 6.0       # air changes per hour with a window open
OUTDOOR_TEMP     = 7.0       # °C, rough November value for Lausanne


@dataclass
class Scenario:
    name: str
    ach_day: float           # background ventilation, awake hours
    ach_night: float         # background ventilation, at night (doors closed)
    ventilates_at: float     # CO2 level at which occupants may open a window (0 = never)
    rh_base: float           # baseline relative humidity, %


SCENARIOS = {
    "normal": Scenario("normal", ach_day=0.8, ach_night=0.7, ventilates_at=1200, rh_base=42),
    "stuffy": Scenario("stuffy", ach_day=0.5, ach_night=0.35, ventilates_at=0, rh_base=48),
    "dry":    Scenario("dry",    ach_day=0.9, ach_night=0.8, ventilates_at=1200, rh_base=24),
}


def scenario_for(day: datetime, choice: str, seed: int) -> Scenario:
    """Fixed scenario, or for 'mixed' a deterministic pick per calendar day."""
    if choice != "mixed":
        return SCENARIOS[choice]
    r = random.Random(f"{seed}-{day.date().isoformat()}").random()
    return SCENARIOS["normal"] if r < 0.7 else SCENARIOS["stuffy"] if r < 0.85 else SCENARIOS["dry"]


def occupancy(t: datetime) -> tuple[int, bool]:
    """(people at home, are they asleep) for a two-person household."""
    h = t.hour + t.minute / 60
    weekend = t.weekday() >= 5
    if h < (8.5 if weekend else 7) or h >= 23:
        return 2, True
    if weekend:
        return (0, False) if 14 <= h < 17 else (2, False)
    if 8.5 <= h < 17.5:
        return 0, False
    guests = 1 if t.weekday() == 4 and 19 <= h < 22 else 0   # Friday dinner guest
    return 2 + guests, False


class Room:
    """State of the simulated room. Call step() with local time and Δt."""

    def __init__(self, volume_m3: float = 45.0, seed: int = 42) -> None:
        self.v = volume_m3
        self.rng = random.Random(seed)
        self.co2 = 650.0          # true CO2, ppm
        self.voc = 20.0           # TVOC above baseline, ppb
        self.temp = 20.5
        self.rh = 40.0
        self.window_until: datetime | None = None
        self.motion = False

    def step(self, t: datetime, dt_s: float, sc: Scenario) -> None:
        dt_h = dt_s / 3600
        people, asleep = occupancy(t)
        h = t.hour + t.minute / 60

        # Window behaviour: occupants who are awake may air the room
        window_open = self.window_until is not None and t < self.window_until
        if (not window_open and sc.ventilates_at and people and not asleep
                and self.co2 > sc.ventilates_at and self.rng.random() < 0.15 * dt_s / 60):
            self.window_until = t + timedelta(minutes=self.rng.randint(8, 15))
            window_open = True

        ach = (sc.ach_night if asleep else sc.ach_day) + (ACH_WINDOW_OPEN if window_open else 0)

        # CO2 mass balance
        gen = people * (GEN_ASLEEP if asleep else GEN_AWAKE)
        self.co2 += (gen * 1e6 / self.v - ach * (self.co2 - CO2_OUTDOOR)) * dt_h

        # VOC: cooking 18:45-19:30 when someone is home, plus people
        cooking = people and not asleep and 18.75 <= h < 19.5
        voc_src = (1150 if cooking else 0) + people * 8
        self.voc += (voc_src - ach * self.voc) * dt_h
        self.voc = max(self.voc, 0)

        # Temperature: heating set-point, body heat, cold air through the window
        setpoint = 19.0 if asleep else (19.5 if people == 0 else 21.0)
        target = OUTDOOR_TEMP if window_open else setpoint + 0.25 * people
        # (a short airing cools the air by ~1-2 °C; walls and furniture keep the heat)
        self.temp += (target - self.temp) * min(1, dt_h / (1.5 if window_open else 1.0))

        # Relative humidity: baseline + people, cooking, morning shower; windows dry
        shower = not asleep and people and 7.0 <= h < 7.4
        rh_target = sc.rh_base + 2.0 * people + (10 if cooking else 0) + (18 if shower else 0)
        if window_open:
            rh_target = min(rh_target, 30)
        self.rh += (rh_target - self.rh) * min(1, dt_h / 0.7)

        # PIR: high hit rate when awake at home
        p_motion = 0.0 if people == 0 else (0.03 if asleep else 0.7)
        self.motion = self.rng.random() < p_motion

    def reading(self, t: datetime) -> dict:
        """What the device would report, including sensor noise and eCO2 bias."""
        n = self.rng.gauss
        eco2 = 400 + 0.85 * (self.co2 - CO2_OUTDOOR) + 0.8 * self.voc + n(0, 20)
        day = t.timestamp() / 86400
        return {
            "temperature": round(self.temp + n(0, 0.05), 1),
            "humidity":    round(min(95, max(10, self.rh + n(0, 0.4))), 1),
            "pressure":    round(963 + 4 * math.sin(day * 2 * math.pi / 5) + n(0, 0.1), 1),
            "eco2":        int(max(400, eco2)),
            "tvoc":        int(max(0, 25 + self.voc + n(0, 6))),
            "motion":      self.motion,
        }


# ── Generation ────────────────────────────────────────────────────────────────

def generate(start: datetime, end: datetime, step_s: int, room: Room, scenario: str, seed: int):
    """Yield (utc timestamp, reading) from start to end, after a 1-day warm-up."""
    t = start - timedelta(days=1)
    while t < end:
        local = t.astimezone(LOCAL_TZ)
        room.step(local, step_s, scenario_for(local, scenario, seed))
        if t >= start:
            yield t, room.reading(local)
        t += timedelta(seconds=step_s)


# ── Backend client ────────────────────────────────────────────────────────────

class Client:
    def __init__(self, url: str, api_key: str, device_id: str) -> None:
        self.url = url.rstrip("/")
        self.headers = {"Content-Type": "application/json", "X-API-Key": api_key,
                        "X-Device-Id": device_id}

    def _request(self, method: str, path: str, body: dict | None = None, timeout: float = 15):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=self.headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or b"null")

    def wait_until_ready(self, timeout_s: int = 90) -> None:
        deadline = time.time() + timeout_s
        while True:
            try:
                self._request("GET", "/health", timeout=3)
                return
            except (urllib.error.URLError, ConnectionError, OSError):
                if time.time() > deadline:
                    sys.exit(f"Backend at {self.url} did not become ready in {timeout_s}s")
                time.sleep(2)

    def has_recent_data(self) -> bool:
        return bool(self._request("GET", "/api/history?hours=2"))

    def send_batch(self, rows: list[tuple[datetime, dict]]) -> None:
        readings = [{"timestamp": ts.isoformat(), **r} for ts, r in rows]
        self._request("POST", "/api/sensor_data/batch", {"readings": readings}, timeout=60)

    def send_live(self, reading: dict) -> dict:
        return self._request("POST", "/api/sensor_data", reading)


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_backfill(args, client: Client, room: Room) -> None:
    if not args.force and client.has_recent_data():
        print("[sim] Recent data already present; skipping backfill (use --force to add anyway)")
        return
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    batch, sent = [], 0
    for item in generate(start, end, args.step, room, args.scenario, args.seed):
        batch.append(item)
        if len(batch) == 500:
            client.send_batch(batch)
            sent += len(batch)
            batch = []
            time.sleep(2.1)            # stay well under the batch rate limit
    if batch:
        client.send_batch(batch)
        sent += len(batch)
    print(f"[sim] Backfilled {sent} readings covering {args.days} day(s)")


def cmd_live(args, client: Client, room: Room) -> None:
    print(f"[sim] Streaming live readings every {args.interval}s (scenario: {args.scenario}, "
          f"speed ×{args.speed}). Ctrl+C to stop.")
    sim_t = datetime.now(timezone.utc)
    while True:
        dt = args.interval * args.speed
        sim_t += timedelta(seconds=dt)
        local = sim_t.astimezone(LOCAL_TZ)
        room.step(local, dt, scenario_for(local, args.scenario, args.seed))
        reading = room.reading(local)
        try:
            resp = client.send_live(reading)
            print(f"[sim] {local:%a %H:%M} eCO2={reading['eco2']:>4} TVOC={reading['tvoc']:>3} "
                  f"T={reading['temperature']} RH={reading['humidity']} → {resp.get('ai_advice', '')[:60]}")
        except (urllib.error.URLError, OSError) as exc:
            print(f"[sim] Upload failed ({exc}); retrying next cycle")
        time.sleep(args.interval)


def cmd_export(args, room: Room) -> None:
    end = datetime.now(timezone.utc)
    rows = generate(end - timedelta(days=args.days), end, args.step, room, args.scenario, args.seed)
    with open(args.out, "w", newline="") as f:
        writer = None
        for ts, r in rows:
            row = {"timestamp": ts.isoformat(), **r}
            if writer is None:
                writer = csv.DictWriter(f, fieldnames=list(row))
                writer.writeheader()
            writer.writerow(row)
    print(f"[sim] Wrote {args.out}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Virtual AuraSense device")
    p.add_argument("command", choices=["run", "backfill", "live", "export"], nargs="?", default="run")
    p.add_argument("--url", default=os.getenv("AURASENSE_URL", "http://localhost:5001"))
    p.add_argument("--api-key", default=os.getenv("AURASENSE_API_KEY", ""))
    p.add_argument("--device-id", default=os.getenv("SIM_DEVICE_ID", "sim-01"))
    p.add_argument("--scenario", default=os.getenv("SIM_SCENARIO", "mixed"),
                   choices=["mixed", *SCENARIOS])
    p.add_argument("--days", type=int, default=7, help="history to backfill/export")
    p.add_argument("--step", type=int, default=60, help="seconds between backfilled readings")
    p.add_argument("--interval", type=float, default=10, help="seconds between live uploads")
    p.add_argument("--speed", type=float, default=1, help="simulated seconds per real second (live)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--force", action="store_true", help="backfill even if data exists")
    p.add_argument("--out", default="readings.csv")
    args = p.parse_args(argv)

    room = Room(seed=args.seed)
    if args.command == "export":
        cmd_export(args, room)
        return

    client = Client(args.url, args.api_key, args.device_id)
    client.wait_until_ready()
    if args.command in ("run", "backfill"):
        cmd_backfill(args, client, room)
    if args.command in ("run", "live"):
        cmd_live(args, client, room)


if __name__ == "__main__":
    main()

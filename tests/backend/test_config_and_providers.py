"""Provider selection happens at import time, so each case runs in a subprocess."""

import json
import os
import subprocess
import sys

from conftest import BACKEND

from services.mock_services import MockTTSService, rule_based_advice


def _config(env: dict, cfg: dict | None = None, tmp_path=None):
    full_env = {k: v for k, v in os.environ.items()
                if k not in ("STORAGE_BACKEND", "AI_PROVIDER", "WEATHER_PROVIDER", "TTS_PROVIDER")}
    full_env["AURASENSE_CONFIG"] = "/nonexistent"
    if cfg is not None:
        path = tmp_path / "config.json"
        path.write_text(json.dumps(cfg))
        full_env["AURASENSE_CONFIG"] = str(path)
    full_env.update(env)
    code = ("from config import Config as C; import json; print(json.dumps([C.STORAGE_BACKEND, "
            "C.AI_PROVIDER, C.WEATHER_PROVIDER, C.TTS_PROVIDER, bool(C.API_KEY)]))")
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=full_env,
                         capture_output=True, text=True)
    return out


def test_no_configuration_means_offline_demo():
    out = _config({})
    assert json.loads(out.stdout.splitlines()[-1])[:4] == ["sqlite", "mock", "mock", "mock"]


def test_existing_config_json_keeps_real_providers(tmp_path):
    cfg = {"gemini_api_key": "g", "openweather_api_key": "o", "gcp_project": "p", "api_key": "s"}
    out = _config({"AURASENSE_API_KEY": ""}, cfg, tmp_path)
    assert json.loads(out.stdout.splitlines()[-1]) == ["bigquery", "gemini", "openweather", "edge", True]


def test_environment_overrides_config_json(tmp_path):
    out = _config({"AI_PROVIDER": "mock", "STORAGE_BACKEND": "sqlite"},
                  {"gemini_api_key": "g", "gcp_project": "p"}, tmp_path)
    assert json.loads(out.stdout.splitlines()[-1])[:2] == ["sqlite", "mock"]


def test_real_provider_without_key_fails_fast():
    out = _config({"AI_PROVIDER": "gemini"})
    assert out.returncode != 0 and "requires GEMINI_API_KEY" in out.stderr


def test_rule_based_advice_priorities():
    assert "open a window now" in rule_based_advice(eco2=1600, tvoc=900)       # CO2 danger first
    assert "TVOC" in rule_based_advice(eco2=700, tvoc=700)
    assert "4 °C outside" in rule_based_advice(eco2=900, outdoor_temp=4.2)
    assert "dry" in rule_based_advice(eco2=500, indoor_hum=25)
    assert "No action needed" in rule_based_advice(indoor_temp=21, indoor_hum=45, eco2=600, tvoc=50)


def test_mock_tts_is_valid_device_audio():
    import io
    import wave
    with wave.open(io.BytesIO(MockTTSService().text_to_wav("hello"))) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        assert 0.3 < w.getnframes() / 16000 < 0.5

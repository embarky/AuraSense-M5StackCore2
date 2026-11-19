import io
import wave
from unittest import mock

import pytest
from conftest import AUTH


def _is_wav(data: bytes) -> bool:
    with wave.open(io.BytesIO(data)) as w:
        return w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2


def test_voice_returns_device_ready_wav(client, wav_bytes):
    r = client.post("/voice", data=wav_bytes, headers=AUTH)
    assert r.status_code == 200 and r.mimetype == "audio/wav" and _is_wav(r.data)


def test_voice_rejects_empty_audio(client):
    assert client.post("/voice", data=b"RIFF", headers=AUTH).status_code == 400


def test_speak_and_alert_return_wav(client):
    for path, body in (("/speak", {"sensor_data": {"temperature": 21, "humidity": 40}}),
                       ("/alert", {"sensor_data": {"eco2": 1800}, "anomaly_type": "co2_danger"})):
        r = client.post(path, json=body, headers=AUTH)
        assert r.status_code == 200 and _is_wav(r.data), path


def test_wav_header_is_parsed(client, wav_bytes):
    """Regression: a typo (getsSpampwidth) made header parsing always fail."""
    with mock.patch("routes.voice.log") as log:
        client.post("/voice", data=wav_bytes, headers=AUTH)
    assert not log.warning.called


def test_errors_do_not_leak_details(client, app, wav_bytes):
    with mock.patch.object(app.gemini_service, "send_audio", side_effect=RuntimeError("secret detail")):
        r = client.post("/voice", data=wav_bytes, headers=AUTH)
    assert r.status_code == 500 and b"secret" not in r.data


@pytest.fixture
def gemini_app(app, monkeypatch):
    """The real GeminiService with the Google client mocked out."""
    from services import gemini_service
    with mock.patch.object(gemini_service.genai, "Client") as client_cls:
        response = mock.MagicMock()
        response.text = "HEARD: what is the CO2?\n[en] It is fine."
        client_cls.return_value.models.generate_content.return_value = response
        app.gemini_service = gemini_service.GeminiService()
        yield app


def test_conversation_history_is_per_device(gemini_app, wav_bytes):
    """Each device's request only carries its own previous turns to the model."""
    c = gemini_app.test_client()
    svc = gemini_app.gemini_service
    generate = svc._client.models.generate_content
    sent = []
    for device in ("kitchen", "bedroom", "kitchen", "bedroom"):
        assert c.post("/voice", data=wav_bytes, headers={**AUTH, "X-Device-Id": device}).status_code == 200
        sent.append(len(generate.call_args.kwargs["contents"]))
    # history turns + the new audio message: 0+1, 0+1, 2+1, 2+1
    assert sent == [1, 1, 3, 3]
    assert len(svc._histories["kitchen"]) == 4 and len(svc._histories["bedroom"]) == 4

    c.post("/reset", headers={**AUTH, "X-Device-Id": "kitchen"})
    assert "kitchen" not in svc._histories and "bedroom" in svc._histories


def test_conversation_history_is_bounded(gemini_app, wav_bytes, monkeypatch):
    from config import Config
    monkeypatch.setattr(Config, "MAX_CONVERSATION_TURNS", 2)
    c = gemini_app.test_client()
    for i in range(6):
        c.post("/voice", data=wav_bytes, headers=AUTH, environ_base={"REMOTE_ADDR": f"192.0.2.{i}"})
    assert len(gemini_app.gemini_service._histories["default"]) == 4

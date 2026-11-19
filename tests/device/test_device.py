# Device firmware tests. Runs under MicroPython (see run_device_tests.sh),
# with the M5Stack hardware modules replaced by the stand-ins in stubs/.
import config
import requests
import connectivity

failures = []


def check(name, fn):
    try:
        fn()
        print("PASS", name)
    except Exception as e:
        failures.append(name)
        print("FAIL", name, "-", repr(e))


def auth_headers_on_every_request():
    config.API_KEY = "secret"
    config.DEVICE_ID = "core2-test"
    connectivity.is_connected = lambda: True
    del requests.calls[:]
    connectivity.upload_sensor_data({"temperature": 21.0, "eco2": None})
    connectivity.fetch_forecast()
    connectivity.speak_announcement({}, {}, [])
    connectivity.speak_alert({}, "co2_danger")
    f = open("rec.wav", "wb")
    f.write(b"RIFF" + b"\0" * 100)
    f.close()
    connectivity.upload_voice_and_receive("rec.wav")
    assert len(requests.calls) == 5, requests.calls
    for _, url, h in requests.calls:
        assert h["X-API-Key"] == "secret" and h["X-Device-Id"] == "core2-test", url
    types = [h.get("Content-Type") for _, _, h in requests.calls]
    assert types == ["application/json", None, "application/json", "application/json", "audio/wav"], types


def old_config_without_new_fields():
    del config.API_KEY
    del config.DEVICE_ID
    h = connectivity._headers()
    assert h["X-API-Key"] == "" and h["X-Device-Id"] == "core2-01"


def clock_uses_backend_offset():
    import time
    import main
    assert main._utc_offset == 3600
    main._safe_update_outdoor({"location": "Lausanne", "utc_offset": 7200})
    assert main._utc_offset == 7200
    for bad in ({"utc_offset": "x"}, {"utc_offset": 99999999}, {"location": "L"}):
        main._safe_update_outdoor(bad)
        assert main._utc_offset == 7200, bad
    main._utc_offset = 3600
    base = time.localtime(time.time())
    local = main._local_time()
    assert (local[3] - base[3]) % 24 == 1, (base, local)
    assert len(main._time_str()) == 5 and main._date_str()


def location_is_kept_when_backend_omits_it():
    import main
    main._outdoor = {}
    main._safe_update_outdoor({"location": "Lausanne, CH"})
    main._safe_update_outdoor({"outdoor_temp": 5})
    assert main._outdoor["location"] == "Lausanne, CH"


def wifi_setup_writes_valid_config():
    from pages import settings
    template = open("config.example.py").read()
    cases = [("HomeWiFi", "simple123"), ('my "wifi"', "pa'ss\"word\\x"),
             ("Café-5G", "äöü 密码"), ("", "")]
    for ssid, pwd in cases:
        f = open("config.py", "w")
        f.write(template)
        f.close()
        settings._save_wifi(ssid, pwd)
        ns = {}
        exec(open("config.py").read(), ns)
        assert ns["WIFI_SSID"] == ssid and ns["WIFI_PASSWORD"] == pwd, (ssid, pwd)
        assert ns["SERVER_PORT"] == 5001 and "API_KEY" in ns


check("auth headers on every backend request", auth_headers_on_every_request)
check("old config.py without API_KEY/DEVICE_ID", old_config_without_new_fields)
check("clock uses DST-aware backend offset", clock_uses_backend_offset)
check("location kept when backend omits it", location_is_kept_when_backend_omits_it)
check("WiFi setup writes a valid config.py", wifi_setup_writes_valid_config)

print("%d failed" % len(failures))
if failures:
    raise SystemExit(1)

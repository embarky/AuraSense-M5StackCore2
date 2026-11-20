# Device setup

How to flash the AuraSense firmware onto an M5Stack Core2 and connect it to a backend: the local Docker stack on your laptop or the cloud deployment.

## What you need

| Item | Notes |
|---|---|
| M5Stack Core2 (or Core2 for AWS IoT EduKit) | ESP32, screen, microphone and speaker built in |
| SGP30 unit → **Port A** | eCO₂ and TVOC |
| AS312 PIR unit → **Port B** | Motion |
| ENV III unit → **Port C** | Temperature, humidity, pressure |
| USB-C data cable | Some cables only charge |
| [M5Burner](https://docs.m5stack.com/en/download) | Flashes the UIFlow 2 firmware |
| [Thonny](https://thonny.org/) (or `pip install mpremote`) | Copies the Python files to the device |
| 2.4 GHz WiFi | The ESP32 cannot join 5 GHz networks |

If the Core2 does not appear as a serial port, install the USB-serial driver (CH9102 or CP210x, depending on the board revision) from the M5Stack download page.

## 1. Flash UIFlow 2

1. Open M5Burner, choose **Core2** in the device list and select the **UIFlow2.0** firmware.
2. Download version **2.4.4** (the version AuraSense was built and tested on).
3. Connect the Core2, pick its serial port and click **Burn**. You can leave the WiFi fields empty.

## 2. Configure

```bash
cp device/config.example.py device/config.py
```

Edit `device/config.py`:

| Setting | Local Docker stack | Cloud deployment |
|---|---|---|
| `WIFI_SSID`, `WIFI_PASSWORD` | Your 2.4 GHz network (or leave empty and use WiFi setup on the device, below) | same |
| `SERVER_HOST` | Your laptop's LAN IP, e.g. `192.168.1.23` (macOS: `ipconfig getifaddr en0`) | Your server's address |
| `SERVER_PORT` | `5001` | The port your proxy exposes |
| `API_KEY` | `local-demo-key`, or `AURASENSE_API_KEY` from your `.env` | `AURASENSE_API_KEY` from the server's `.env` |
| `DEVICE_ID` | Any name, e.g. `core2-01` | same |

`device/config.py` is gitignored, so your WiFi password and key stay out of the repository.

## 3. Upload the files

The firmware is the contents of `device/`: `main.py`, `boot.py`, `config.py`, `sensors.py`, `connectivity.py`, `components.py` and the `pages/` folder. Skip any `__pycache__` folders.

**With Thonny:** Tools → Options → Interpreter → *MicroPython (ESP32)* and the Core2's port. Press Stop to get a `>>>` prompt. In the Files pane, open the device's `/flash` folder, select the files and `pages/` on the computer side, right-click → **Upload to /flash**, and replace the existing `main.py` and `boot.py`.

**With mpremote:**

```bash
cd device
PORT=/dev/cu.usbserial-XXXX     # ls /dev/cu.* to find it; Linux: /dev/ttyUSB0 or /dev/ttyACM0
mpremote connect $PORT cp main.py boot.py config.py sensors.py connectivity.py components.py :/flash/
mpremote connect $PORT cp -r pages :/flash/
```

## 4. Run `main.py` on boot

UIFlow 2 shows its own startup menu by default. To boot straight into AuraSense, run this once in the Thonny shell (or with `mpremote connect $PORT exec "..."`):

```python
import esp32
nvs = esp32.NVS("uiflow"); nvs.set_u8("boot_option", 0); nvs.commit()
```

Then press the reset button. To get the UIFlow menu back, hold button A while resetting.

## 5. Start a backend

**Local stack, no cloud account.** Run only the backend and dashboard so the simulator does not mix its data with the device's; `down -v` clears the simulator's history first:

```bash
docker compose down -v
docker compose up --build backend dashboard
```

The laptop and the Core2 must be on the same network. If macOS asks whether to accept incoming connections for Docker, allow it. Readings appear on http://localhost:8501 within about 30 seconds. With the mock providers, advice is rule-based and voice replies are a chime; set `AI_PROVIDER`, `TTS_PROVIDER` and `WEATHER_PROVIDER` in `.env`, with the matching API keys, to use the real services.

**Cloud deployment.** See [operations.md](operations.md).

## Using the device

| Button | Short press | Long press |
|---|---|---|
| A (left) | Previous page | WiFi setup |
| B (centre) | Home page | — |
| C (right) | Next page | Hold to ask the voice assistant; release to send |

**WiFi setup without editing `config.py`:** long-press A. The device opens a hotspot called `AuraSense-Setup` and shows a QR code. Scan it with your phone, enter the network name and password on the page that opens, and the device saves them to `config.py` and restarts.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| "No SSID Configured" or "WiFi FAILED" on screen | Empty or wrong WiFi details, or a 5 GHz-only network. Use WiFi setup (long-press A) |
| Connected to WiFi but no data on the dashboard | Wrong `SERVER_HOST`, laptop on a different network, or a firewall blocking port 5001. Test from a phone on the same WiFi: `http://<SERVER_HOST>:5001/health` |
| Backend log shows `401` | `API_KEY` on the device does not match `AURASENSE_API_KEY` on the backend |
| A sensor reads `--` | Unit in the wrong port. SGP30 → A, PIR → B, ENV III → C |
| eCO₂ stays at 400 ppm for the first 15 s | Normal: the SGP30 warms up before reporting real values |
| The UIFlow menu appears instead of AuraSense | `boot_option` is not 0. Repeat step 4 |

Version 1 of the firmware ran on the device throughout the course project. The v2 firmware changes are small and covered by the MicroPython tests in CI, but have not yet been re-run on hardware (see [design.md](design.md#7-verification)).

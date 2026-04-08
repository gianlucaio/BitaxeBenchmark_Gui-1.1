# Bitaxe Hashrate Benchmark — GUI Edition

A Python-based benchmarking tool with a graphical interface for optimizing Bitaxe mining performance. Tests different voltage and frequency combinations while monitoring hashrate, temperature, and power efficiency — with full support for both **single-chip** (5V barrel jack) and **dual-chip** models (GT 800, GT 801, Duo 650 — 12V XT30).

> This project is a fork of [mrv777/Bitaxe-Hashrate-Benchmark](https://github.com/mrv777/Bitaxe-Hashrate-Benchmark), which is itself a fork of [WhiteyCookie/Bitaxe-Hashrate-Benchmark](https://github.com/WhiteyCookie/Bitaxe-Hashrate-Benchmark).

---

## What's new in this fork

| Feature | Original CLI | This GUI fork |
|---|---|---|
| Interface | Command line only | Graphical window (tkinter) |
| Dual-chip support (GT 800/801, Duo 650) | ❌ | ✅ |
| Auto-detection of chip count | ❌ | ✅ (multi-signal heuristic) |
| Manual chip mode override | `--model-profile` flag | Radio button in GUI |
| Custom PSU wattage limit | Hardcoded 40 W | Editable field |
| Custom temp / VR temp limits | Hardcoded | Editable fields |
| Custom voltage step | Hardcoded 20 mV | Editable field (5–100 mV) |
| Custom frequency step | Hardcoded 25 MHz | Editable field (5–100 MHz) |
| Input voltage range | 5 V only (4800–5500 mV) | Auto-adjusted per profile |
| Reset to defaults | ❌ | ✅ One-click button |
| Real-time coloured log | Terminal only | Scrollable log panel |
| Stop benchmark mid-run | Ctrl+C only | Stop button |

---

## Supported models

| Model | Chip | PSU | Profile |
|---|---|---|---|
| Bitaxe Max (1xx) | BM1397 | 5 V barrel jack | single |
| Bitaxe Ultra (2xx) | BM1366 | 5 V barrel jack | single |
| Bitaxe Supra (4xx) | BM1368 | 5 V barrel jack | single |
| Bitaxe Gamma 6xx | BM1370 | 5 V barrel jack | single |
| **Bitaxe GT 800** | 2× BM1370 | **12 V XT30** | **dual** |
| **Bitaxe GT 801** | 2× BM1370 | **12 V XT30** | **dual** |
| **Bitaxe Duo 650** | 2× BM1370 | **12 V XT30** | **dual** |
| Bitaxe Hex (3xx / 7xx) | 6× BM1366/1368 | 12 V XT30 | dual |

---

## Prerequisites

- Python **3.11** or higher
- `tkinter` (included with most Python distributions)
- Access to a Bitaxe miner on your local network (WiFi 2.4 GHz)
- Git (optional)

### Installing tkinter if missing

```bash
# Debian / Ubuntu / Raspberry Pi OS
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter

# macOS (via Homebrew)
brew install python-tk

# Windows
# tkinter is bundled with the official python.org installer — no extra step needed
```

---

## Installation

### Standard installation

```bash
# 1. Clone this repository
git clone https://github.com/<your-username>/Bitaxe-Hashrate-Benchmark.git
cd Bitaxe-Hashrate-Benchmark

# 2. Create and activate a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Usage

### Launch the GUI

```bash
python bitaxe_hashrate_benchmark_gui.py
```

The window opens immediately. No command-line arguments are required.

### GUI walkthrough

#### 1. Connection
Enter the local IP address of your Bitaxe (e.g. `192.168.1.42`).  
Find it in your router's DHCP table or on the AxeOS OLED display.

#### 2. Chip detection
Choose how the tool identifies your hardware:

| Option | When to use |
|---|---|
| **Auto (recommended)** | Works for most devices. Reads `asicCount`, scans all API string fields for board keywords (`gt`, `duo`, `800`, `801`, `650`…), and falls back to a live hashrate heuristic (> 1500 GH/s → dual). |
| **Single chip** | Force 5 V profile if auto-detect picks the wrong mode. |
| **Dual chip** | Force 12 V profile — use this for GT 800/801 and Duo 650 if auto-detect fails. |

#### 3. Starting settings
All fields are editable before each run:

| Field | Default | Range | Description |
|---|---|---|---|
| Initial voltage (mV) | 1150 | 1000–1400 | Starting core voltage. The tool increments from here. |
| Initial frequency (MHz) | 500 | 400–1200 | Starting clock frequency. The tool increments from here. |
| PSU max wattage (W) | 60 | 10–500 | Hard ceiling for power draw. Set this to your PSU's rated output. |
| Max chip temp (°C) | 66 | 40–90 | Per-chip cutoff. On dual-chip models the hottest chip is used. |
| Max VR temp (°C) | 86 | 40–110 | Voltage-regulator cutoff. Monitors `vrTemp` and `vrTemp2`. |
| Voltage step (mV) | 20 | 5–100 | How much voltage increases when a combination is unstable. Smaller steps = finer scan, longer runtime. |
| Frequency step (MHz) | 25 | 5–100 | How much frequency increases between stable combinations. Smaller steps = finer scan, longer runtime. |

> **Runtime note:** smaller steps produce more combinations. With 10 MHz frequency steps instead of 25, the range 500–800 MHz generates 30 combinations instead of 12 — roughly 5–6 hours of benchmark time instead of 2.

#### 4. Buttons

- **↺ Reset to defaults** — restores all fields to their factory values without clearing the log or stopping a run.
- **▶ Start benchmark** — validates inputs, connects to the Bitaxe, and begins the automated sweep.
- **⏹ Stop benchmark** — requests a clean stop after the current sample completes, applies the best settings found so far, and saves results.
- **🗑 Clear log** — clears the output panel without affecting the running benchmark.

---

## How the benchmark works

1. Connects to the Bitaxe API (`/api/system/info`, `/api/system/asic`) and detects the hardware profile.
2. Applies the starting voltage and frequency, then restarts the device and waits **90 seconds** for stabilisation.
3. Runs each combination for **10 minutes**, sampling every **15 seconds** (40 samples total).
4. Validates that the average hashrate is within **6 %** of the theoretical maximum for the current frequency and core count.
5. If stable → increases frequency by the configured **frequency step** (default 25 MHz) and repeats.  
   If unstable → increases voltage by the configured **voltage step** (default 20 mV), steps frequency back by one step, and retries.  
   If a safety limit is hit → stops immediately.
6. After all combinations are tested (or a limit is reached), applies the highest-hashrate stable configuration automatically.
7. Saves full results to a JSON file.

---

## Safety features

- **Per-chip temperature monitoring** — on dual-chip models, both `temp` and `temp2` are read; the hottest chip is always the limit.
- **Dual VRM monitoring** — reads both `vrTemp` and `vrTemp2`; the hottest is the limit.
- **Profile-aware input voltage check** — single-chip: 4800–5500 mV; dual-chip: 11000–13500 mV. Prevents false alarms on 12 V boards.
- **User-defined PSU wattage limit** — benchmark stops if measured power exceeds your PSU rating.
- **Temperature floor** — readings below 5 °C are rejected as sensor errors.
- **Outlier removal** — 3 highest and 3 lowest hashrate samples are discarded before averaging.
- **Warmup exclusion** — first 6 temperature readings are excluded to avoid cold-start bias.
- **Hashrate sanity check** — if average hashrate deviates more than 6 % from the theoretical value the combination is marked unstable.
- **Graceful stop** — pressing Stop or closing the window applies the best settings found so far before exiting.
- **Dual-chip `asicCount` correction** — if the firmware incorrectly reports `asicCount=1` on a dual-chip board, the tool detects the mismatch and forces the correct value for hashrate calculations, logging a warning.

---

## Output

Results are saved to:

```
bitaxe_benchmark_<ip>_<timestamp>.json
```

The JSON contains:

```json
{
  "profile": "Dual-chip (GT 800/801, Duo 650 — 12V XT30)",
  "all_results": [ ... ],
  "top_performers": [
    {
      "rank": 1,
      "coreVoltage": 1200,
      "frequency": 600,
      "averageHashRate": 2850.4,
      "averageTemperature": 61.2,
      "averageVRTemp": 74.8,
      "efficiencyJTH": 15.3
    },
    ...
  ],
  "most_efficient": [ ... ]
}
```

Each entry includes average hashrate, temperature(s), VR temperature (when available), power efficiency in J/TH, and the active hardware profile.

---

## Configuration reference

### GUI fields (editable before each run, restored by Reset to defaults)

| Field | Default | Range | Description |
|---|---|---|---|
| Initial voltage | 1150 mV | 1000–1400 mV | Starting core voltage |
| Initial frequency | 500 MHz | 400–1200 MHz | Starting clock frequency |
| PSU max wattage | 60 W | 10–500 W | Power draw ceiling |
| Max chip temp | 66 °C | 40–90 °C | Per-chip temperature cutoff |
| Max VR temp | 86 °C | 40–110 °C | Voltage-regulator temperature cutoff |
| Voltage step | 20 mV | 5–100 mV | Increment when voltage needs to increase |
| Frequency step | 25 MHz | 5–100 MHz | Increment between stable frequency levels |

### Fixed constants (edit in source if needed)

| Constant | Value | Description |
|---|---|---|
| `SLEEP_TIME` | 90 s | Stabilisation wait after each restart |
| `BENCHMARK_TIME` | 600 s | Duration of each combination test (10 min) |
| `SAMPLE_INTERVAL` | 15 s | Time between samples |
| `MAX_ALLOWED_VOLTAGE` | 1400 mV | Absolute ceiling for core voltage |
| `MIN_ALLOWED_VOLTAGE` | 1000 mV | Absolute floor for core voltage |
| `MAX_ALLOWED_FREQ` | 1200 MHz | Absolute ceiling for frequency |
| `MIN_ALLOWED_FREQ` | 400 MHz | Absolute floor for frequency |
| `SINGLE_CHIP_VMIN/VMAX` | 4800–5500 mV | Input voltage range for 5 V barrel jack models |
| `DUAL_CHIP_VMIN/VMAX` | 11000–13500 mV | Input voltage range for 12 V XT30 models |
| `DUAL_CHIP_HASHRATE_THRESHOLD_GHS` | 1500 GH/s | Live hashrate above which auto-detect infers dual-chip |

---

## Data processing details

- Outlier removal: 3 highest and 3 lowest hashrate readings removed before averaging.
- Warmup exclusion: first 6 temperature readings discarded.
- Hashrate validation: average must be ≥ 94 % of theoretical maximum (`frequency × total_cores / 1000`).
- Power averaging: all samples used (no trimming).
- Efficiency: calculated as `avg_power_W / (avg_hashrate_GHs / 1000)` → J/TH.

---

## Contributing

Contributions are welcome. Please open an issue first to discuss what you would like to change, then submit a Pull Request against the `main` branch.

If you own a model not yet listed in the supported table, reports of your API response fields (especially `ASICModel`, `boardVersion`, `asicCount`) are very helpful for improving auto-detection.

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.

---

## Disclaimer

This tool runs your Bitaxe outside its factory parameters. Overclocking and voltage modifications can damage hardware if done without adequate cooling or with an undersized power supply. Always ensure your PSU wattage limit is set correctly in the GUI before starting. The authors accept no responsibility for hardware damage.

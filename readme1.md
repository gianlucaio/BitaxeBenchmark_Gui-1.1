# BitaxeBenchGui v1.7

**Bitaxe All-Model Hashrate Benchmark — GUI Edition**

A dark-themed, Bitcoin-orange desktop tool for systematically benchmarking every voltage × frequency combination on your Bitaxe ASIC miner and finding the optimal configuration automatically.

Supports single-chip models (Gamma, Supra, Ultra — 5 V barrel jack) and dual-chip models (GT 800/801, Duo 650 — 12 V XT30).

---

## ✨ What's New in v1.7

### 🐛 Bug Fixes
- Division by zero protection in efficiency calculation when hashrate = 0
- Timeout accumulo fix: Global retry counter prevents infinite retry loops
- Chart overflow prevention: Live hashrate chart now limited to last 200 data points

### 🚀 New Features
- **Auto-save every N steps**: Configurable interval (default 10) — saves partial JSON during long benchmarks so you can resume if interrupted
- **Preset profiles**: Save/load entire configurations with custom names — perfect for "Conservative", "Aggressive", "Efficiency" profiles
- **Export Markdown**: Generate GitHub-flavored .md report with tables & summary ready to share
- **Safety auto-stop**: If temperature rises >3°C in 30 seconds, pauses for 2 minutes and retries; aborts benchmark after 2 violations
- **Comparison mode**: Load two JSONs side-by-side in a dedicated window to compare before/after hardware mods
- **Heatmap click details**: Click any cell in the heatmap to see full step info in a popup

---

## Requirements

| Requirement | Notes |
|-------------|-------|
| Python 3.11+ | `python3 --version` |
| tkinter | Usually bundled. Linux: `sudo apt install python3-tk` |
| Bitaxe running AxeOS | Firmware 2.x recommended (exposes errorPercentage) |

No other dependencies. All other modules used (`csv`, `json`, `threading`, `queue`, `math`, `os`, `pathlib`, `datetime`) are part of the Python standard library.

---

## Quick Start

```bash
python3 BitaxeBenchGui_1_7.py
```

1. Enter the Bitaxe IP address (e.g. 192.168.1.100)
2. Set your starting voltage, frequency, steps and ceilings
3. (Optional) Load a saved preset or configure auto-save interval
4. Press ▶ **Start Benchmark**
5. When finished, the best configuration is applied automatically and results are saved as JSON + CSV + Markdown

---

## GUI Overview

### Configuration Panel

| Field | Description |
|-------|-------------|
| Bitaxe IP address | Local IP of the miner (no http://) |
| Chip detection | Auto (recommended), Single chip, or Dual chip |
| Initial voltage (mV) | Starting core voltage for the sweep |
| Initial frequency (MHz) | Starting clock frequency for the sweep |
| PSU max wattage (W) | Safety ceiling — benchmark stops the step if exceeded |
| Max chip temp (°C) | Safety ceiling for die temperature |
| Max VR temp (°C) | Safety ceiling for VR temperature |
| Voltage step (mV) | Increment between voltage levels |
| Frequency step (MHz) | Increment between frequency steps |
| Max voltage (mV) | Upper bound for the voltage sweep |
| Max frequency (MHz) | Upper bound for the frequency sweep |
| Max error rate (%) | Steps above this threshold are flagged as discarded in analysis (default 1.0 %) |
| Early-stop steps | If hashrate drops for N consecutive frequency steps, skip to next voltage (0 = disabled) |
| Auto-save interval | 🆕 Save partial results every N steps (0 = disabled, default 10) |
| ☑ Adaptive warm-up | Wait for temperature to stabilise instead of fixed 40 s timer |

### Preset Management 🆕

| Button | Action |
|--------|--------|
| 💾 Save | Save current configuration as a named preset |
| 📂 Load | Load a previously saved preset |
| 🗑 Delete | Remove a preset from disk |

Presets are stored in `~/.bitaxe_bench_presets/` as JSON files.

**Example presets**:
- **Conservative**: Low voltage, narrow range, high safety margins
- **Aggressive**: High voltage ceiling, wide sweep, tight error threshold
- **Efficiency**: Medium voltage, focus on low J/TH sweet spot

### Buttons

| Button | Action |
|--------|--------|
| !et | Restore all fields to defaults |
| ▶ Start Benchmark | Validate settings and start a fresh sweep |
| #ume | Load a partial JSON from a previous interrupted run and continue from where it stopped |
| 📊 Analyse Results | Open the analysis window for any benchmark JSON |
| & | 🆕 Load two JSONs side-by-side to compare benchmarks |
| 📄 Export CSV | Export current or loaded results to a CSV file |
| ⏹ Stop Benchmark | Gracefully stop after the current sample finishes |

### Progress Bar & ETA
A progress bar below the status line shows percentage complete and estimated time remaining, calculated from the number of tested steps vs total planned steps (voltage levels × frequency levels).

### Live Hashrate Chart
A real-time sparkline updates every sample interval during the benchmark, showing the hashrate trend across all steps tested so far. Limited to last 200 points to prevent memory/performance issues.

---

## How the Benchmark Works

### 2-D Voltage × Frequency Sweep (v1.5+)

For each voltage level from `start_v` to `max_v` (stepping by `v_step`):

1. Reset frequency to `start_f`
2. Apply voltage / frequency to the device via `PATCH /api/system`
3. Restart the device
4. Wait for warm-up (adaptive or fixed)
5. Sample the device every 15 s for ~500 s total (~33 samples)
6. Record hashrate, temperature, VR temp, power, error rate
7. 🆕 **Thermal safety check**: If temp rises >3°C in 30s, pause 2 min & retry
8. 🆕 **Auto-save**: If step count is multiple of auto-save interval, save partial JSON
9. Advance frequency by `f_step` and repeat from step 2
10. After finishing all frequencies (or early-stop), advance voltage and repeat

Every combination is tested independently. An unstable hashrate does not abort the frequency sweep — it is recorded with `stable: false` and the next step continues.

### Safety Limits (Abort Current Step)

If any of these are exceeded during sampling, the current voltage level is abandoned and the benchmark moves to the next voltage:

- Chip temperature ≥ Max chip temp
- VR temperature ≥ Max VR temp
- Power draw > PSU max wattage
- Input voltage outside valid range for the detected profile
- Hashrate or power data unavailable from API
- 🆕 Thermal safety violation (2 rapid temp rises in same benchmark)

### Adaptive Warm-Up (v1.6)

When enabled, instead of waiting a fixed 40 s after restart, the tool polls the chip temperature every 10 s and waits until two consecutive readings differ by less than ±1 °C. Always waits at least 20 s for the device to boot. Falls back to an 80 s ceiling if temperature never stabilises.

### Early-Stop on Declining Hashrate (v1.6)

If Early-stop steps is set to N > 0, the frequency sweep for a given voltage level stops early when hashrate declines for N consecutive steps. This avoids wasting time on clearly declining regions of the frequency space and moves to the next voltage faster.

### Resume (v1.6)

If a benchmark run is interrupted (power cut, crash, manual stop), press #ume, select the partial JSON file, and the benchmark will skip all already-tested (voltage, frequency) pairs and continue from the first untested combination.

### Auto-Save 🆕 (v1.7)

Every N steps (default 10), a partial JSON is saved as `bitaxe_benchmark_<ip>_<datetime>_PARTIAL.json`. If the benchmark is interrupted, you can load this file via #ume and continue where you left off. Set interval to 0 to disable.

---

## Output Files

Three files are saved automatically when the benchmark finishes or is stopped:

### JSON — `bitaxe_benchmark_<ip>_<datetime>.json`

```json
{
  "profile": "Dual-chip (GT 800/801, Duo 650 — 12V XT30)",
  "sweep": "2D voltage × frequency",
  "all_results": [
    {
      "coreVoltage": 1230,
      "frequency": 650,
      "averageHashRate": 2650.8,
      "averageTemperature": 61.4,
      "efficiencyJTH": 18.47,
      "profile": "...",
      "stable": true,
      "averageVRTemp": 58.0,
      "averageErrorRate": 0.702
    },
    ...
  ],
  "top_performers": [...],
  "most_efficient": [...]
}
```

### CSV — `bitaxe_benchmark_<ip>_<datetime>.csv`

Same data as `all_results` in tabular form, directly openable in Excel or LibreOffice Calc. Columns: `coreVoltage`, `frequency`, `averageHashRate`, `averageTemperature`, `efficiencyJTH`, `stable`, `averageVRTemp`, `averageErrorRate`, `profile`.

### Markdown 🆕 — `bitaxe_benchmark_<ip>_<datetime>.md`

GitHub-flavored Markdown report with:
- Profile & timestamp
- Best hashrate configuration
- Most efficient configuration
- Top 5 by hashrate (table)
- Top 5 by efficiency (table)

Perfect for sharing results in GitHub issues, Discord, or documentation.

---

## Analysis Window

Open via 📊 Analyse Results. Two tabs:

### Tab 1 — Results Table

Full table of every tested step, colour-coded by error rate:

| Colour | Meaning |
|--------|---------|
| 🟢 Dark green | Optimal — error rate 0.20–0.70 % |
| 🟠 Dark orange | Acceptable — error rate 0.70–1.00 % |
| 🔴 Dark red | Discarded — error rate > 1.00 % |
| 🟡 Gold | ★ Best step |
| ⬛ Dark blue | No error data from firmware |

The ★ Best step is selected by preferring the optimal window first, then acceptable steps, sorted by lowest J/TH (best efficiency). If no error data is available, it falls back to the overall best efficiency.

### Tab 2 — Heatmap 🔥

An interactive voltage × frequency grid where each cell is coloured by either:
- **Hashrate (GH/s)** — blue = low, red = high
- **Efficiency (J/TH)** — red = low (best), blue = high (worst)

Toggle between modes with the radio buttons. Cell values are printed inside each cell when the grid is large enough. A colour scale bar is shown on the right edge.

🆕 **Click any cell to see a detailed popup with**:
- Voltage / Frequency
- Hashrate, Power, Efficiency
- Chip temp, VR temp
- Error rate
- Stable status

---

## Comparison Mode 🆕

Open via &. Load two benchmark JSONs (e.g., before/after a hardware mod) and view them side-by-side:

- Profile & total steps
- Best hashrate config
- Most efficient config
- Top 5 by hashrate
- Top 5 by efficiency

Perfect for evaluating:
- Different cooling solutions
- Firmware versions
- PSU changes
- Thermal pad mods

---

## Error Rate Sources

The tool reads error rate in priority order:

1. `errorPercentage` — direct AxeOS field, matches the dashboard UI exactly (AxeOS 2.12+)
2. `asicErrorRate` — older field name used in some firmware forks
3. Delta of `hashrateMonitor.asics[n].errorCount` between consecutive samples — per-chip increment, used as fallback when neither field is available

Cumulative `sharesRejected / sharesAccepted` are intentionally not used — they grow from boot and are meaningless within a single benchmark step.

---

## Supported Models

| Model | Profile | Input voltage |
|-------|---------|---------------|
| Gamma, Supra, Ultra | Single-chip | 4.8–5.5 V |
| GT 800, GT 801 | Dual-chip | 11.8–12.2 V |
| Duo 650 | Dual-chip | 11.8–12.2 V |

Model detection is automatic (reads `asicCount` and API string fields). Can be overridden manually in the GUI.

---

## Changelog

### v1.7 (2025-04-XX)

**🐛 Bug Fixes**:
- Division by zero protection in efficiency calculation
- Global retry counter prevents timeout accumulo
- Chart limited to last 200 points to prevent memory issues

**✨ New Features**:
- Auto-save partial results every N steps (configurable, default 10)
- Preset profiles (save/load configurations with custom names)
- Export Markdown report (GitHub-flavored tables)
- Safety auto-stop: pause & retry on rapid temp rise, abort after 2 violations
- Comparison mode: side-by-side analysis of two benchmarks
- Heatmap click-to-details: popup with full step info

### v1.6
- Progress bar with step count and ETA
- Live hashrate sparkline chart during benchmark
- Early-stop on consecutive declining hashrate steps (configurable)
- Adaptive warm-up: waits for temperature stability instead of fixed timer
- Resume from partial JSON: skip already-tested combinations
- CSV export (automatic on finish + manual export button)
- Configurable error-rate threshold in GUI
- Completion sound (system bell / winsound)
- Heatmap tab in Analysis window (hashrate or J/TH, togglable)

### v1.5
- Fixed 2-D voltage × frequency sweep (old code was 1-D diagonal)
- Fixed error rate: reads errorPercentage directly from AxeOS
- Per-chip errorCount delta as secondary error source
- Unstable steps recorded instead of silently skipped
- `_apply_best` and `_print_summary` prefer stable results
- JSON includes sweep field and stable boolean per entry

### v1.4
- `max_voltage` and `max_frequency` fields in GUI

### v1.3
- Error-rate sampling every iteration
- `averageErrorRate` in JSON output
- Analysis window with colour-coded table and best-step card
- Dark Bitcoin-themed GUI

---

## FAQ

### How long does a benchmark take?

**Example**: With voltage range 1150–1300 mV (step 20) and frequency range 500–700 MHz (step 25):

- Voltage levels: 8
- Frequency levels: 9
- Total steps: 72
- Time per step: ~8.5 minutes (500s benchmark + 40s warmup)
- **Total time: ~10 hours**

**Tips to reduce time**:
- Enable adaptive warm-up (saves ~20s per step on low voltages)
- Enable early-stop (skips declining frequencies)
- Increase step sizes (e.g., 25 mV / 50 MHz for a quick sweep)
- Use auto-save so you can stop/resume overnight

### What if the benchmark crashes?

If auto-save is enabled (default), a `_PARTIAL.json` file is saved every 10 steps. Press #ume, select that file, and the benchmark continues from the last checkpoint.

### Can I benchmark multiple Bitaxe devices?

Not in the same session. Run the tool once per device. Use Comparison Mode afterwards to compare results side-by-side.

### What's the difference between "stable" and "unstable" steps?

A step is marked stable if the measured hashrate is ≥94% of the theoretical hashrate for that voltage/frequency. Unstable steps are still recorded in the JSON but are deprioritised when selecting the best configuration.

### Why do some steps show "—" for error rate?

Older firmware versions don't expose `errorPercentage` or `asicErrorRate`. The tool falls back to per-chip `errorCount` delta, but if that's also unavailable, error rate is reported as `None` and the step is marked "no data" in the analysis window.

### Is overclocking safe?

**No.** Voltages above the manufacturer's specification can degrade or destroy the ASIC chip. This tool is for advanced users who understand the risks. Start conservatively (within spec) and monitor temperatures closely. Use the safety auto-stop feature and set conservative `max_temp` / `max_vr_temp` values.

---

## License

MIT License — see [LICENSE](LICENSE) file for details.

---

## Contributing

Pull requests welcome! For major changes, please open an issue first to discuss what you'd like to change.

**Roadmap ideas**:
- Multi-Bitaxe batch mode
- PDF export with charts
- Desktop notifications (email/Telegram)
- ML-based auto-tuner (Bayesian optimization)

---

## Credits

Developed by the Bitaxe community.

Bitcoin-orange dark theme inspired by the official Bitcoin Design Guide.

---

## Disclaimer

⚠️ **Overclocking may damage hardware.** Voltages above the manufacturer's recommended range can permanently degrade or destroy the ASIC chip. Use this tool at your own risk. Start conservatively and increase limits gradually. Always monitor temperatures and stop immediately if anything looks abnormal.

The authors are not responsible for any hardware damage, loss of mining revenue, or voided warranties resulting from use of this software.

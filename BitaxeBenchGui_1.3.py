"""
Bitaxe Hashrate Benchmark — GUI Edition  v1.3
Supports single-chip (5V) and dual-chip models (GT 800/801, Duo 650 — 12V XT30).

New in v1.3
  • Error-rate sampling (asicErrorRate / rejectRate / shares) every iteration
  • averageErrorRate stored in the JSON for every step
  • 📊 Analyse Results button: loads any benchmark JSON, finds the true best
    step after filtering steps with error rate > 1 %, shows full table and
    highlights the optimal configuration (highest HR + lowest J/TH + errors in
    the 0.20–0.70 % sweet spot)
  • Restyled GUI: dark Bitcoin-inspired theme, coloured header, accent buttons
"""

import requests
import time
import json
import sys
import threading
import queue
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox, filedialog
except ImportError:
    print("ERROR: tkinter not found. Install it with: sudo apt install python3-tk")
    sys.exit(1)

# ---------------------------------------------------------------------------
# DEFAULTS — shown in GUI, user can edit before starting
# ---------------------------------------------------------------------------
DEFAULTS = {
    "ip":                  "",
    "voltage":             1150,
    "frequency":           500,
    "max_psu_watts":       60,
    "max_temp":            66,
    "max_vr_temp":         86,
    "chip_mode":           "auto",
    "voltage_increment":   20,
    "frequency_increment": 25,
}

# Benchmark constants
VOLTAGE_INCREMENT    = DEFAULTS["voltage_increment"]
FREQUENCY_INCREMENT  = DEFAULTS["frequency_increment"]
SLEEP_TIME           = 90
BENCHMARK_TIME       = 600
SAMPLE_INTERVAL      = 15
MAX_ALLOWED_VOLTAGE  = 1400
MIN_ALLOWED_VOLTAGE  = 1000
MAX_ALLOWED_FREQ     = 1200
MIN_ALLOWED_FREQ     = 400

SINGLE_CHIP_VMIN = 4800
SINGLE_CHIP_VMAX = 5500
DUAL_CHIP_VMIN   = 11000
DUAL_CHIP_VMAX   = 13500

DUAL_CHIP_KEYWORDS = ["gt", "duo", "800", "801", "650", "dual", "2chip"]
DUAL_CHIP_HASHRATE_THRESHOLD_GHS = 1500

# Error-rate thresholds (%)
ERR_MAX_VALID   = 1.0    # steps above this are discarded
ERR_OPT_LOW     = 0.20   # optimal window low
ERR_OPT_HIGH    = 0.70   # optimal window high

# ---------------------------------------------------------------------------
# Colour palette (dark Bitcoin theme)
# ---------------------------------------------------------------------------
C = {
    "bg":          "#111827",   # main window background
    "panel":       "#1f2937",   # frame / labelframe bg
    "card":        "#374151",   # spinbox / entry bg
    "accent":      "#f7931a",   # Bitcoin orange
    "accent_dark": "#c4760e",   # pressed-state orange
    "text":        "#f3f4f6",   # primary text
    "muted":       "#9ca3af",   # secondary text
    "green":       "#22c55e",
    "yellow":      "#f59e0b",
    "red":         "#ef4444",
    "blue":        "#3b82f6",
    "log_bg":      "#0d1117",   # log area background
    "separator":   "#374151",
}


# ---------------------------------------------------------------------------
# Benchmark engine (runs in a background thread)
# ---------------------------------------------------------------------------

class BitaxeBenchmark:
    def __init__(self, config: dict, log_queue: queue.Queue):
        self.cfg         = config
        self.q           = log_queue
        self.stop_event  = threading.Event()

        self.bitaxe_url        = f"http://{config['ip']}"
        self.profile           = None
        self.small_core_count  = None
        self.asic_count        = None
        self.default_voltage   = None
        self.default_frequency = None
        self.results           = []
        self.start_time        = datetime.now().strftime("%Y-%m-%d_%H-%M")

    # ------------------------------------------------------------------ log
    def _log(self, msg: str, color: str = "white"):
        self.q.put(("log", msg, color))

    def _status(self, msg: str):
        self.q.put(("status", msg))

    # ------------------------------------------------------------ API calls
    def _get(self, endpoint: str, timeout: int = 10):
        for attempt in range(3):
            if self.stop_event.is_set():
                return None
            try:
                r = requests.get(f"{self.bitaxe_url}{endpoint}", timeout=timeout)
                r.raise_for_status()
                return r.json()
            except requests.exceptions.Timeout:
                self._log(f"Timeout {endpoint} (attempt {attempt+1}/3)", "yellow")
            except requests.exceptions.ConnectionError:
                self._log(f"Connection error {endpoint} (attempt {attempt+1}/3)", "red")
            except requests.exceptions.RequestException as e:
                self._log(f"Request error {endpoint}: {e}", "red")
                break
            time.sleep(5)
        return None

    def _patch_settings(self, voltage: int, frequency: int) -> bool:
        try:
            r = requests.patch(
                f"{self.bitaxe_url}/api/system",
                json={"coreVoltage": voltage, "frequency": frequency},
                timeout=10,
            )
            r.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            self._log(f"Error applying settings: {e}", "red")
            return False

    def _restart(self, wait: bool = True):
        try:
            requests.post(f"{self.bitaxe_url}/api/system/restart", timeout=10)
            if wait:
                self._log(f"Restarting — waiting {SLEEP_TIME}s for stabilisation…", "yellow")
                for i in range(SLEEP_TIME):
                    if self.stop_event.is_set():
                        return
                    time.sleep(1)
        except requests.exceptions.RequestException as e:
            self._log(f"Restart error: {e}", "red")

    def _set_and_restart(self, voltage: int, frequency: int, wait: bool = True):
        self._log(f"  → {voltage}mV / {frequency}MHz", "yellow")
        if self._patch_settings(voltage, frequency):
            self._restart(wait=wait)

    # --------------------------------------------------- model detection ---
    def _all_string_values(self, d: dict) -> list[str]:
        out = []
        for v in d.values():
            if isinstance(v, str):
                out.append(v.lower())
            elif isinstance(v, dict):
                out.extend(self._all_string_values(v))
        return out

    def _detect_profile(self, system_info: dict, current_hashrate_ghs: float | None) -> dict:
        chip_mode = self.cfg["chip_mode"]
        if chip_mode == "single":
            self._log("Profile: forced SINGLE-chip by user.", "green")
            return self._make_profile("single")
        if chip_mode == "dual":
            self._log("Profile: forced DUAL-chip by user.", "green")
            return self._make_profile("dual")

        api_asic = system_info.get("asicCount")
        if api_asic is not None and int(api_asic) >= 2:
            self._log(f"Auto-detect: asicCount={api_asic} → DUAL-chip.", "green")
            return self._make_profile("dual")

        all_strings = self._all_string_values(system_info)
        for kw in DUAL_CHIP_KEYWORDS:
            for s in all_strings:
                if kw in s:
                    self._log(f"Auto-detect: found keyword '{kw}' in API field → DUAL-chip.", "green")
                    return self._make_profile("dual")

        if current_hashrate_ghs and current_hashrate_ghs > DUAL_CHIP_HASHRATE_THRESHOLD_GHS:
            self._log(
                f"Auto-detect: live hashrate {current_hashrate_ghs:.0f} GH/s "
                f"> {DUAL_CHIP_HASHRATE_THRESHOLD_GHS} GH/s → DUAL-chip.", "green",
            )
            return self._make_profile("dual")

        self._log("Auto-detect: no dual-chip signal found → SINGLE-chip.", "green")
        return self._make_profile("single")

    def _make_profile(self, kind: str) -> dict:
        max_psu = self.cfg["max_psu_watts"]
        if kind == "dual":
            return {
                "kind":              "dual",
                "label":             "Dual-chip (GT 800/801, Duo 650 — 12V XT30)",
                "min_input_voltage": DUAL_CHIP_VMIN,
                "max_input_voltage": DUAL_CHIP_VMAX,
                "max_power":         max_psu,
                "max_temp":          self.cfg["max_temp"],
                "max_vr_temp":       self.cfg["max_vr_temp"],
            }
        return {
            "kind":              "single",
            "label":             "Single-chip (Gamma/Supra/Ultra — 5V barrel jack)",
            "min_input_voltage": SINGLE_CHIP_VMIN,
            "max_input_voltage": SINGLE_CHIP_VMAX,
            "max_power":         max_psu,
            "max_temp":          self.cfg["max_temp"],
            "max_vr_temp":       self.cfg["max_vr_temp"],
        }

    # ------------------------------------------------ fetch initial state --
    def _fetch_settings(self) -> bool:
        self._status("Connecting to Bitaxe…")
        info = self._get("/api/system/info")
        if info is None:
            self._log("Cannot reach Bitaxe. Check IP and WiFi.", "red")
            return False

        if "smallCoreCount" not in info:
            self._log("Error: smallCoreCount missing from API. Cannot continue.", "red")
            return False

        self.small_core_count = info["smallCoreCount"]
        live_hr = info.get("hashRate")
        self.profile = self._detect_profile(info, live_hr)

        has_v  = "coreVoltage" in info
        has_f  = "frequency"   in info
        has_ac = "asicCount"   in info

        if has_v and has_f and has_ac:
            self.default_voltage   = info["coreVoltage"]
            self.default_frequency = info["frequency"]
            self.asic_count        = info["asicCount"]
        else:
            self._log("Fetching remaining info from /api/system/asic…", "yellow")
            asic = self._get("/api/system/asic")
            if asic is None:
                self._log("Cannot fetch /api/system/asic. Cannot continue.", "red")
                return False
            self.default_voltage   = asic.get("defaultVoltage",   1150)
            self.default_frequency = asic.get("defaultFrequency", 500)
            self.asic_count        = asic.get("asicCount",        1)

        if self.profile["kind"] == "dual" and (not self.asic_count or self.asic_count < 2):
            self._log(
                f"WARNING: API reports asicCount={self.asic_count} but profile is dual-chip. "
                "Forcing asicCount=2 for hashrate calculation.", "yellow",
            )
            self.asic_count = 2

        total_cores = self.small_core_count * self.asic_count
        self._log("─" * 54, "white")
        self._log(f"Profile      : {self.profile['label']}", "green")
        self._log(f"ASIC count   : {self.asic_count}  (total cores: {total_cores})", "green")
        self._log(f"Default      : {self.default_voltage}mV / {self.default_frequency}MHz", "green")
        self._log(f"Input voltage: {self.profile['min_input_voltage']}–{self.profile['max_input_voltage']} mV", "green")
        self._log(f"Max PSU      : {self.profile['max_power']} W", "green")
        self._log(f"Max chip temp: {self.profile['max_temp']} °C", "green")
        self._log(f"Max VR temp  : {self.profile['max_vr_temp']} °C", "green")
        self._log("─" * 54, "white")
        return True

    # ----------------------------------------------------- temp helpers ---
    def _get_max_temp(self, info: dict):
        temps = [info.get("temp"), info.get("temp2")]
        valid = [t for t in temps if t is not None]
        return max(valid) if valid else None

    def _get_max_vr_temp(self, info: dict):
        vrs   = [info.get("vrTemp"), info.get("vrTemp2")]
        valid = [t for t in vrs if t is not None and t > 0]
        return max(valid) if valid else None

    # ------------------------------------------------- error-rate helper --
    def _get_error_rate(self, info: dict) -> float | None:
        """
        Returns the ASIC error rate as a percentage (0–100), or None if the
        firmware does not expose it.

        Priority:
          1. Direct percentage field — recent AxeOS firmware may expose
             'asicErrorRate', 'rejectRate', or 'errorRate' directly.
          2. Calculated from cumulative share counters
             'sharesAccepted' + 'sharesRejected'.
        """
        for field in ("asicErrorRate", "rejectRate", "errorRate"):
            val = info.get(field)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass

        accepted = info.get("sharesAccepted")
        rejected = info.get("sharesRejected")
        if accepted is not None and rejected is not None:
            total = int(accepted) + int(rejected)
            if total > 0:
                return (int(rejected) / total) * 100.0

        return None

    # -------------------------------------------------- benchmark loop ---
    def _benchmark_iteration(self, voltage: int, frequency: int):
        """
        Returns (avg_hashrate, avg_temp, efficiency_jth, hashrate_ok,
                 avg_vr_temp, avg_error_rate, error_reason)
        avg_error_rate is None when the firmware does not expose error data.
        """
        p           = self.profile
        expected_hr = frequency * (self.small_core_count * self.asic_count / 1000)

        hash_rates, temperatures, powers, vr_temps_list, error_rates = [], [], [], [], []
        total_samples = BENCHMARK_TIME // SAMPLE_INTERVAL

        self._status(f"Testing {voltage}mV / {frequency}MHz…")

        for sample in range(total_samples):
            if self.stop_event.is_set():
                return None, None, None, False, None, None, "STOPPED"

            info = self._get("/api/system/info")
            if info is None:
                return None, None, None, False, None, None, "SYSTEM_INFO_FAILURE"

            temp       = self._get_max_temp(info)
            vr_temp    = self._get_max_vr_temp(info)
            voltage_in = info.get("voltage")
            hash_rate  = info.get("hashRate")
            power      = info.get("power")
            err_rate   = self._get_error_rate(info)

            # --- safety checks ---
            if temp is None:
                return None, None, None, False, None, None, "TEMPERATURE_DATA_FAILURE"
            if temp < 5:
                return None, None, None, False, None, None, "TEMPERATURE_BELOW_5"
            if temp >= p["max_temp"]:
                self._log(f"⚠ Chip temp {temp:.0f}°C ≥ {p['max_temp']}°C — stopping.", "red")
                return None, None, None, False, None, None, "CHIP_TEMP_EXCEEDED"
            if vr_temp is not None and vr_temp >= p["max_vr_temp"]:
                self._log(f"⚠ VR temp {vr_temp:.0f}°C ≥ {p['max_vr_temp']}°C — stopping.", "red")
                return None, None, None, False, None, None, "VR_TEMP_EXCEEDED"
            if voltage_in is not None:
                if voltage_in < p["min_input_voltage"]:
                    self._log(
                        f"⚠ Input voltage {voltage_in} mV below {p['min_input_voltage']} mV "
                        f"({p['label']}) — stopping.", "red"
                    )
                    return None, None, None, False, None, None, "INPUT_VOLTAGE_BELOW_MIN"
                if voltage_in > p["max_input_voltage"]:
                    self._log(
                        f"⚠ Input voltage {voltage_in} mV above {p['max_input_voltage']} mV — stopping.", "red"
                    )
                    return None, None, None, False, None, None, "INPUT_VOLTAGE_ABOVE_MAX"
            if hash_rate is None or power is None:
                return None, None, None, False, None, None, "HASHRATE_POWER_DATA_FAILURE"
            if power > p["max_power"]:
                self._log(f"⚠ Power {power:.1f}W > {p['max_power']}W PSU limit — stopping.", "red")
                return None, None, None, False, None, None, "POWER_EXCEEDED"

            hash_rates.append(hash_rate)
            temperatures.append(temp)
            powers.append(power)
            if vr_temp is not None:
                vr_temps_list.append(vr_temp)
            if err_rate is not None:
                error_rates.append(err_rate)

            pct  = (sample + 1) / total_samples * 100
            line = (
                f"[{sample+1:2d}/{total_samples}] {pct:5.1f}% | "
                f"{voltage}mV {frequency}MHz | "
                f"HR: {hash_rate:.0f} GH/s | "
                f"T: {temp:.0f}°C"
            )
            if vr_temp is not None:
                line += f" VR: {vr_temp:.0f}°C"
            line += f" | {power:.1f}W"
            if err_rate is not None:
                err_color = "red" if err_rate > ERR_MAX_VALID else ("yellow" if err_rate > ERR_OPT_HIGH else "green")
                self._log(line, "white")
                self._log(f"         Err: {err_rate:.3f}%", err_color)
            else:
                self._log(line, "white")

            if sample < total_samples - 1:
                time.sleep(SAMPLE_INTERVAL)

        if not hash_rates:
            return None, None, None, False, None, None, "NO_DATA_COLLECTED"

        # trim outliers
        s_hr    = sorted(hash_rates)
        trim_hr = s_hr[3:-3] if len(s_hr) > 6 else s_hr
        avg_hr  = sum(trim_hr) / len(trim_hr)

        s_t     = sorted(temperatures)
        trim_t  = s_t[6:] if len(s_t) > 6 else s_t
        avg_temp = sum(trim_t) / len(trim_t)

        avg_vr = None
        if vr_temps_list:
            s_vr   = sorted(vr_temps_list)
            trim_v = s_vr[6:] if len(s_vr) > 6 else s_vr
            avg_vr = sum(trim_v) / len(trim_v)

        avg_pwr = sum(powers) / len(powers)

        # average error rate (no trimming — keep all samples)
        avg_err = (sum(error_rates) / len(error_rates)) if error_rates else None

        if avg_hr <= 0:
            return None, None, None, False, None, avg_err, "ZERO_HASHRATE"

        eff_jth = avg_pwr / (avg_hr / 1000)
        hr_ok   = avg_hr >= expected_hr * 0.94

        self._log(f"  Avg HR   : {avg_hr:.1f} GH/s  (expected ≥ {expected_hr*0.94:.1f})", "green")
        self._log(f"  Avg temp : {avg_temp:.1f}°C{'  VR: '+f'{avg_vr:.1f}°C' if avg_vr else ''}", "green")
        self._log(f"  Eff      : {eff_jth:.2f} J/TH  |  Power: {avg_pwr:.1f}W", "green")
        if avg_err is not None:
            err_color = "red" if avg_err > ERR_MAX_VALID else ("yellow" if avg_err > ERR_OPT_HIGH else "green")
            self._log(f"  Avg Err  : {avg_err:.3f}%", err_color)

        return avg_hr, avg_temp, eff_jth, hr_ok, avg_vr, avg_err, None

    # ---------------------------------------------------- save / reset ---
    def _save(self):
        ip       = self.cfg["ip"].replace(".", "_")
        filename = f"bitaxe_benchmark_{ip}_{self.start_time}.json"
        try:
            top5_hr  = sorted(self.results, key=lambda x: x["averageHashRate"], reverse=True)[:5]
            top5_eff = sorted(self.results, key=lambda x: x["efficiencyJTH"])[:5]
            data = {
                "profile":        self.profile["label"],
                "all_results":    self.results,
                "top_performers": top5_hr,
                "most_efficient": top5_eff,
            }
            with open(filename, "w") as f:
                json.dump(data, f, indent=4)
            self._log(f"Results saved → {filename}", "green")
        except IOError as e:
            self._log(f"Error saving: {e}", "red")

    def _apply_best(self):
        if not self.results:
            self._log("No results — restoring device defaults.", "yellow")
            self._set_and_restart(self.default_voltage, self.default_frequency, wait=False)
            return
        best = sorted(self.results, key=lambda x: x["averageHashRate"], reverse=True)[0]
        self._log(
            f"Best: {best['coreVoltage']}mV / {best['frequency']}MHz "
            f"→ {best['averageHashRate']:.1f} GH/s", "green"
        )
        self._set_and_restart(best["coreVoltage"], best["frequency"], wait=False)

    def _print_summary(self):
        if not self.results:
            return
        top5 = sorted(self.results, key=lambda x: x["averageHashRate"], reverse=True)[:5]
        self._log("─" * 54, "white")
        self._log("TOP 5 CONFIGURATIONS BY HASHRATE", "green")
        for i, r in enumerate(top5, 1):
            line = (
                f"  #{i}  {r['coreVoltage']}mV / {r['frequency']}MHz → "
                f"{r['averageHashRate']:.1f} GH/s  {r['efficiencyJTH']:.2f} J/TH"
                f"  {r['averageTemperature']:.1f}°C"
            )
            if "averageVRTemp" in r:
                line += f"  VR {r['averageVRTemp']:.1f}°C"
            if "averageErrorRate" in r and r["averageErrorRate"] is not None:
                line += f"  Err {r['averageErrorRate']:.3f}%"
            self._log(line, "green")

    # ----------------------------------------------------------- run ------
    def run(self):
        try:
            if not self._fetch_settings():
                self.q.put(("done", "error"))
                return

            self._log("DISCLAIMER: overclocking may damage hardware. Use at your own risk.", "red")

            cur_v  = self.cfg["voltage"]
            cur_f  = self.cfg["frequency"]
            v_step = self.cfg["voltage_increment"]
            f_step = self.cfg["frequency_increment"]

            while cur_v <= MAX_ALLOWED_VOLTAGE and cur_f <= MAX_ALLOWED_FREQ:
                if self.stop_event.is_set():
                    break

                self._set_and_restart(cur_v, cur_f)
                if self.stop_event.is_set():
                    break

                avg_hr, avg_t, eff, ok, avg_vr, avg_err, err = self._benchmark_iteration(cur_v, cur_f)

                if self.stop_event.is_set():
                    break

                if avg_hr is not None:
                    result = {
                        "coreVoltage":        cur_v,
                        "frequency":          cur_f,
                        "averageHashRate":     avg_hr,
                        "averageTemperature": avg_t,
                        "efficiencyJTH":      eff,
                        "profile":            self.profile["label"],
                    }
                    if avg_vr is not None:
                        result["averageVRTemp"] = avg_vr
                    if avg_err is not None:
                        result["averageErrorRate"] = avg_err
                    self.results.append(result)

                    if ok:
                        if cur_f + f_step <= MAX_ALLOWED_FREQ:
                            cur_f += f_step
                        else:
                            self._log("Reached max frequency — benchmark complete.", "green")
                            break
                    else:
                        if cur_v + v_step <= MAX_ALLOWED_VOLTAGE:
                            cur_v += v_step
                            cur_f  = max(MIN_ALLOWED_FREQ, cur_f - f_step)
                            self._log(
                                f"Hashrate low → voltage ↑ {cur_v}mV, frequency ↓ {cur_f}MHz", "yellow"
                            )
                        else:
                            self._log("Reached max voltage — benchmark complete.", "green")
                            break
                else:
                    self._log(f"Stopping: {err}", "red")
                    break

        except Exception as e:
            self._log(f"Unexpected error: {e}", "red")

        finally:
            self._apply_best()
            if self.results:
                self._save()
                self._print_summary()
            self._status("Benchmark finished.")
            self.q.put(("done", "ok"))


# ---------------------------------------------------------------------------
# Analysis window
# ---------------------------------------------------------------------------

class AnalysisWindow(tk.Toplevel):
    """
    Loads a benchmark JSON file and shows:
      • a full table of all steps (colour-coded by error rate)
      • the single BEST step: highest hashrate among steps with error ≤ 1 %,
        prioritising steps in the optimal 0.20–0.70 % window
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.title("📊 Benchmark Analysis")
        self.configure(bg=C["bg"])
        self.resizable(True, True)
        self.minsize(780, 540)
        self._build_ui()
        self._load_file()

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=C["accent"], height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(
            hdr, text="⛏  BENCHMARK ANALYSIS",
            bg=C["accent"], fg="#111827",
            font=("Courier", 14, "bold"),
        ).pack(side="left", padx=16, pady=10)

        # Best-step card
        self._card_frame = tk.Frame(self, bg=C["panel"], pady=12, padx=14)
        self._card_frame.pack(fill="x", padx=14, pady=(12, 4))
        self._card_label = tk.Label(
            self._card_frame,
            text="Load a JSON file to see results.",
            bg=C["panel"], fg=C["text"],
            font=("Courier", 10), justify="left", anchor="w",
        )
        self._card_label.pack(fill="x")

        # Table frame
        tbl_outer = tk.Frame(self, bg=C["bg"])
        tbl_outer.pack(fill="both", expand=True, padx=14, pady=(4, 14))

        # Column headers
        cols = ("Volt (mV)", "Freq (MHz)", "HR (GH/s)", "Power (W)", "J/TH", "Temp (°C)", "VR Temp", "Err %", "Status")
        self._tree = ttk.Treeview(tbl_outer, columns=cols, show="headings", height=18)
        col_widths = [80, 85, 90, 75, 70, 75, 70, 70, 100]
        for col, w in zip(cols, col_widths):
            self._tree.heading(col, text=col)
            self._tree.column(col, width=w, anchor="center")

        sb = ttk.Scrollbar(tbl_outer, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        # Row colour tags
        self._tree.tag_configure("optimal",     background="#14532d", foreground=C["text"])
        self._tree.tag_configure("acceptable",  background="#422006", foreground=C["text"])
        self._tree.tag_configure("discarded",   background="#450a0a", foreground="#9ca3af")
        self._tree.tag_configure("nodata",      background="#1e293b", foreground=C["muted"])
        self._tree.tag_configure("best",        background="#854d0e", foreground="#fef08a")

        # Legend
        legend = tk.Frame(self, bg=C["bg"])
        legend.pack(fill="x", padx=14, pady=(0, 10))
        defs = [
            ("#14532d", "Optimal (0.20–0.70 %)"),
            ("#422006", "Acceptable (0.70–1.00 %)"),
            ("#450a0a", "Discarded (> 1.00 %)"),
            ("#854d0e", "★ Best step"),
            ("#1e293b", "No error data"),
        ]
        for bg, label in defs:
            dot = tk.Label(legend, text="  ", bg=bg, width=2)
            dot.pack(side="left")
            tk.Label(legend, text=f" {label}   ", bg=C["bg"], fg=C["muted"],
                     font=("Courier", 8)).pack(side="left")

    def _load_file(self):
        path = filedialog.askopenfilename(
            title="Select benchmark JSON file",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            self.destroy()
            return
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Cannot read file:\n{e}", parent=self)
            self.destroy()
            return

        results = data.get("all_results", [])
        if not results:
            messagebox.showwarning("Empty", "No results found in the JSON file.", parent=self)
            self.destroy()
            return

        self._populate(results, data.get("profile", "unknown"))

    def _populate(self, results: list, profile: str):
        # Clear tree
        for row in self._tree.get_children():
            self._tree.delete(row)

        # Categorise each step
        valid_steps   = []  # error ≤ 1 %
        optimal_steps = []  # error in 0.20–0.70 %

        for r in results:
            err = r.get("averageErrorRate")
            if err is None:
                tag = "nodata"
            elif err > ERR_MAX_VALID:
                tag = "discarded"
            elif ERR_OPT_LOW <= err <= ERR_OPT_HIGH:
                tag = "optimal"
                valid_steps.append(r)
                optimal_steps.append(r)
            else:
                tag = "acceptable"
                valid_steps.append(r)
            r["_tag"] = tag

        # Pick best step: prefer optimal window first, then acceptable, sorted by J/TH
        pool = optimal_steps if optimal_steps else valid_steps
        best = None
        if pool:
            best = min(pool, key=lambda x: x["efficiencyJTH"])

        # Fall back: if no error data at all, use best J/TH among all
        if best is None:
            no_err_steps = [r for r in results if r.get("averageErrorRate") is None]
            if no_err_steps:
                best = min(no_err_steps, key=lambda x: x["efficiencyJTH"])

        # Populate treeview
        for r in results:
            err     = r.get("averageErrorRate")
            vr_str  = f"{r['averageVRTemp']:.1f}" if "averageVRTemp" in r else "—"
            err_str = f"{err:.3f}" if err is not None else "—"
            tag     = r["_tag"]

            is_best = (best is not None and
                       r["coreVoltage"] == best["coreVoltage"] and
                       r["frequency"]   == best["frequency"])
            if is_best:
                tag = "best"

            self._tree.insert("", "end", values=(
                r["coreVoltage"],
                r["frequency"],
                f"{r['averageHashRate']:.1f}",
                f"{r['averageHashRate'] * r['efficiencyJTH'] / 1000:.1f}",
                f"{r['efficiencyJTH']:.2f}",
                f"{r['averageTemperature']:.1f}",
                vr_str,
                err_str,
                "★ BEST" if is_best else tag.upper().replace("_", " "),
            ), tags=(tag,))

        # Update card
        if best:
            err_b   = best.get("averageErrorRate")
            err_txt = f"{err_b:.3f} %" if err_b is not None else "no data"
            power_b = best["averageHashRate"] * best["efficiencyJTH"] / 1000
            win_msg = (
                f"  ★  BEST CONFIGURATION  ★\n\n"
                f"  Profile   : {profile}\n"
                f"  Voltage   : {best['coreVoltage']} mV\n"
                f"  Frequency : {best['frequency']} MHz\n"
                f"  Hashrate  : {best['averageHashRate']:.1f} GH/s\n"
                f"  Power     : {power_b:.1f} W\n"
                f"  Efficiency: {best['efficiencyJTH']:.2f} J/TH\n"
                f"  Chip temp : {best['averageTemperature']:.1f} °C"
            )
            if "averageVRTemp" in best:
                win_msg += f"\n  VR temp   : {best['averageVRTemp']:.1f} °C"
            win_msg += f"\n  Error rate: {err_txt}"

            pool_name = "optimal window (0.20–0.70 %)" if optimal_steps else \
                        ("valid steps (≤ 1.00 %)" if valid_steps else "all steps (no error data)")
            win_msg += f"\n\n  Selected from: {pool_name}"

            self._card_label.config(text=win_msg, fg=C["yellow"])
        else:
            self._card_label.config(
                text="  No valid steps found (all steps have error rate > 1 %).",
                fg=C["red"]
            )


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BitaxeBenchGui 1.3")
        self.configure(bg=C["bg"])
        self.resizable(True, True)
        self.minsize(660, 640)

        self._benchmark_thread = None
        self._engine           = None
        self._log_queue        = queue.Queue()

        self._apply_theme()
        self._build_ui()
        self._poll_queue()

    # --------------------------------------------------------- ttk theme --
    def _apply_theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        bg   = C["bg"]
        pnl  = C["panel"]
        txt  = C["text"]
        mute = C["muted"]
        acc  = C["accent"]
        card = C["card"]

        style.configure(".",
            background=bg, foreground=txt,
            fieldbackground=card, troughcolor=pnl,
            selectbackground=acc, selectforeground="#111827",
            font=("Courier", 9),
        )
        style.configure("TFrame",      background=bg)
        style.configure("TLabel",      background=bg, foreground=txt)
        style.configure("TLabelframe", background=pnl, foreground=acc,
                        bordercolor=C["separator"], lightcolor=pnl, darkcolor=pnl)
        style.configure("TLabelframe.Label", background=pnl, foreground=acc,
                        font=("Courier", 9, "bold"))

        style.configure("TEntry",   fieldbackground=card, foreground=txt,
                        insertcolor=txt, bordercolor=C["separator"])
        style.configure("TSpinbox", fieldbackground=card, foreground=txt,
                        insertcolor=txt, arrowcolor=acc, bordercolor=C["separator"])
        style.configure("TRadiobutton", background=bg, foreground=txt,
                        indicatorcolor=acc)
        style.map("TRadiobutton",
            background=[("active", pnl)],
            foreground=[("active", acc)],
        )

        # Default button
        style.configure("TButton",
            background=pnl, foreground=txt,
            bordercolor=C["separator"], lightcolor=pnl, darkcolor=pnl,
            relief="flat", padding=(8, 5),
        )
        style.map("TButton",
            background=[("active", card), ("pressed", C["separator"])],
            foreground=[("active", acc)],
        )

        # Orange accent button (Start / Analyse)
        style.configure("Accent.TButton",
            background=acc, foreground="#111827",
            bordercolor=C["accent_dark"], lightcolor=acc, darkcolor=C["accent_dark"],
            relief="flat", padding=(10, 6), font=("Courier", 9, "bold"),
        )
        style.map("Accent.TButton",
            background=[("active", C["accent_dark"]), ("pressed", C["accent_dark"])],
        )

        # Red danger button (Stop)
        style.configure("Danger.TButton",
            background="#7f1d1d", foreground=txt,
            bordercolor="#991b1b", lightcolor="#7f1d1d", darkcolor="#7f1d1d",
            relief="flat", padding=(8, 5),
        )
        style.map("Danger.TButton",
            background=[("active", "#991b1b"), ("disabled", "#374151")],
            foreground=[("disabled", mute)],
        )

        style.configure("TSeparator", background=C["separator"])
        style.configure("TScrollbar",
            background=pnl, troughcolor=bg, arrowcolor=mute,
            bordercolor=bg, lightcolor=pnl, darkcolor=pnl,
        )

        # Treeview for analysis window
        style.configure("Treeview",
            background=C["panel"], foreground=txt,
            fieldbackground=C["panel"], rowheight=22,
            bordercolor=C["separator"],
        )
        style.configure("Treeview.Heading",
            background=C["accent"], foreground="#111827",
            font=("Courier", 8, "bold"), relief="flat",
        )
        style.map("Treeview",
            background=[("selected", acc)],
            foreground=[("selected", "#111827")],
        )

    # -------------------------------------------------------------- UI build
    def _build_ui(self):
        PAD = {"padx": 10, "pady": 4}

        # ── header banner ─────────────────────────────────────────────────
        banner = tk.Frame(self, bg=C["accent"], height=52)
        banner.pack(fill="x")
        banner.pack_propagate(False)
        tk.Label(
            banner, text="⛏  BITAXE BENCHMARK  v1.3",
            bg=C["accent"], fg="#111827",
            font=("Courier", 15, "bold"),
        ).pack(side="left", padx=18, pady=10)
        tk.Label(
            banner, text="open-source ASIC tuning tool",
            bg=C["accent"], fg="#78350f",
            font=("Courier", 8),
        ).pack(side="left", padx=0, pady=16)

        # ── configuration frame ───────────────────────────────────────────
        cfg_frame = ttk.LabelFrame(self, text="  Configuration", padding=10)
        cfg_frame.pack(fill="x", padx=12, pady=(10, 4))
        cfg_frame.columnconfigure(1, weight=1)

        row = 0

        # IP
        ttk.Label(cfg_frame, text="Bitaxe IP address:").grid(row=row, column=0, sticky="w", **PAD)
        self._ip_var = tk.StringVar(value=DEFAULTS["ip"])
        ip_entry = ttk.Entry(cfg_frame, textvariable=self._ip_var, width=22)
        ip_entry.grid(row=row, column=1, sticky="w", **PAD)
        row += 1

        ttk.Separator(cfg_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=6
        )
        row += 1

        # Chip detection
        ttk.Label(cfg_frame, text="Chip detection:").grid(row=row, column=0, sticky="w", **PAD)
        self._chip_var = tk.StringVar(value=DEFAULTS["chip_mode"])
        chip_frame = ttk.Frame(cfg_frame)
        chip_frame.grid(row=row, column=1, columnspan=2, sticky="w")
        for label, val in [("Auto (recommended)", "auto"), ("Single chip", "single"), ("Dual chip", "dual")]:
            ttk.Radiobutton(chip_frame, text=label, variable=self._chip_var, value=val).pack(
                side="left", padx=(0, 12)
            )
        row += 1

        ttk.Separator(cfg_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=6
        )
        row += 1

        ttk.Label(cfg_frame, text="Starting settings", font=("Courier", 9, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w", **PAD
        )
        row += 1

        fields = [
            ("Initial voltage (mV):",      "_v_voltage",    DEFAULTS["voltage"],             MIN_ALLOWED_VOLTAGE, MAX_ALLOWED_VOLTAGE),
            ("Initial frequency (MHz):",   "_v_frequency",  DEFAULTS["frequency"],           MIN_ALLOWED_FREQ,    MAX_ALLOWED_FREQ),
            ("PSU max wattage (W):",        "_v_psu",        DEFAULTS["max_psu_watts"],       10,                  500),
            ("Max chip temp (°C):",         "_v_max_temp",   DEFAULTS["max_temp"],            40,                  90),
            ("Max VR temp (°C):",           "_v_max_vr",     DEFAULTS["max_vr_temp"],         40,                  110),
            ("Voltage step (mV):",          "_v_v_step",     DEFAULTS["voltage_increment"],   5,                   100),
            ("Frequency step (MHz):",       "_v_f_step",     DEFAULTS["frequency_increment"], 5,                   100),
        ]

        for label, attr, default, lo, hi in fields:
            ttk.Label(cfg_frame, text=label).grid(row=row, column=0, sticky="w", **PAD)
            var = tk.IntVar(value=default)
            setattr(self, attr, var)
            spin = ttk.Spinbox(cfg_frame, from_=lo, to=hi, textvariable=var, width=8)
            spin.grid(row=row, column=1, sticky="w", **PAD)
            row += 1

        # Buttons row
        btn_frame = ttk.Frame(cfg_frame)
        btn_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(10, 2))

        ttk.Button(btn_frame, text="↺  Reset", command=self._reset_defaults).pack(
            side="left", padx=(0, 6)
        )
        self._start_btn = ttk.Button(
            btn_frame, text="▶  Start Benchmark",
            command=self._start, style="Accent.TButton"
        )
        self._start_btn.pack(side="left", padx=(0, 6))

        ttk.Button(
            btn_frame, text="📊  Analyse Results",
            command=self._open_analysis, style="Accent.TButton"
        ).pack(side="left")

        # ── status bar ────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Idle — configure above and press Start.")
        status_bar = tk.Label(
            self, textvariable=self._status_var,
            bg=C["panel"], fg=C["muted"],
            anchor="w", padx=8, pady=4,
            font=("Courier", 8),
        )
        status_bar.pack(fill="x", padx=12, pady=(4, 0))

        # ── log area ──────────────────────────────────────────────────────
        log_frame = ttk.LabelFrame(self, text="  Output", padding=4)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(4, 4))

        self._log_text = scrolledtext.ScrolledText(
            log_frame, state="disabled", wrap="word",
            font=("Courier", 9), height=20,
            bg=C["log_bg"], fg=C["text"],
            insertbackground=C["text"],
            selectbackground=C["accent"],
            relief="flat", borderwidth=0,
        )
        self._log_text.pack(fill="both", expand=True)

        # colour tags
        self._log_text.tag_config("green",  foreground=C["green"])
        self._log_text.tag_config("yellow", foreground=C["yellow"])
        self._log_text.tag_config("red",    foreground=C["red"])
        self._log_text.tag_config("white",  foreground=C["text"])

        # ── bottom bar ────────────────────────────────────────────────────
        bot_frame = tk.Frame(self, bg=C["bg"])
        bot_frame.pack(fill="x", padx=12, pady=(0, 10))

        self._stop_btn = ttk.Button(
            bot_frame, text="⏹  Stop Benchmark",
            command=self._stop, state="disabled",
            style="Danger.TButton",
        )
        self._stop_btn.pack(side="left")

        ttk.Button(bot_frame, text="🗑  Clear log", command=self._clear_log).pack(
            side="left", padx=8
        )

    # --------------------------------------------------- defaults reset ---
    def _reset_defaults(self):
        self._ip_var.set(DEFAULTS["ip"])
        self._chip_var.set(DEFAULTS["chip_mode"])
        self._v_voltage.set(DEFAULTS["voltage"])
        self._v_frequency.set(DEFAULTS["frequency"])
        self._v_psu.set(DEFAULTS["max_psu_watts"])
        self._v_max_temp.set(DEFAULTS["max_temp"])
        self._v_max_vr.set(DEFAULTS["max_vr_temp"])
        self._v_v_step.set(DEFAULTS["voltage_increment"])
        self._v_f_step.set(DEFAULTS["frequency_increment"])
        self._append_log("Settings reset to defaults.", "yellow")

    # --------------------------------------------------------- log helpers
    def _append_log(self, msg: str, color: str = "white"):
        self._log_text.config(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_text.insert("end", f"[{ts}] {msg}\n", color)
        self._log_text.see("end")
        self._log_text.config(state="disabled")

    def _clear_log(self):
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    # --------------------------------------------------- queue polling ---
    def _poll_queue(self):
        try:
            while True:
                item = self._log_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    _, msg, color = item
                    self._append_log(msg, color)
                elif kind == "status":
                    _, msg = item
                    self._status_var.set(msg)
                elif kind == "done":
                    self._on_benchmark_done()
        except queue.Empty:
            pass
        self.after(200, self._poll_queue)

    # ------------------------------------------------------ validation ---
    def _validate(self) -> dict | None:
        ip = self._ip_var.get().strip()
        if not ip:
            messagebox.showerror("Missing IP", "Please enter the Bitaxe IP address.")
            return None

        try:
            v      = self._v_voltage.get()
            f      = self._v_frequency.get()
            psu    = self._v_psu.get()
            mt     = self._v_max_temp.get()
            mvr    = self._v_max_vr.get()
            v_step = self._v_v_step.get()
            f_step = self._v_f_step.get()
        except tk.TclError:
            messagebox.showerror("Invalid input", "All numeric fields must be valid integers.")
            return None

        errors = []
        if not (MIN_ALLOWED_VOLTAGE <= v <= MAX_ALLOWED_VOLTAGE):
            errors.append(f"Voltage must be {MIN_ALLOWED_VOLTAGE}–{MAX_ALLOWED_VOLTAGE} mV.")
        if not (MIN_ALLOWED_FREQ <= f <= MAX_ALLOWED_FREQ):
            errors.append(f"Frequency must be {MIN_ALLOWED_FREQ}–{MAX_ALLOWED_FREQ} MHz.")
        if psu < 10:
            errors.append("PSU wattage must be ≥ 10 W.")
        if not (40 <= mt <= 90):
            errors.append("Max chip temp must be 40–90 °C.")
        if not (40 <= mvr <= 110):
            errors.append("Max VR temp must be 40–110 °C.")
        if not (5 <= v_step <= 100):
            errors.append("Voltage step must be 5–100 mV.")
        if not (5 <= f_step <= 100):
            errors.append("Frequency step must be 5–100 MHz.")
        if errors:
            messagebox.showerror("Validation error", "\n".join(errors))
            return None

        return {
            "ip":                  ip,
            "voltage":             v,
            "frequency":           f,
            "max_psu_watts":       psu,
            "max_temp":            mt,
            "max_vr_temp":         mvr,
            "chip_mode":           self._chip_var.get(),
            "voltage_increment":   v_step,
            "frequency_increment": f_step,
        }

    # --------------------------------------------------------- start/stop
    def _start(self):
        cfg = self._validate()
        if cfg is None:
            return

        self._start_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._status_var.set("Benchmark running…")
        self._append_log("=" * 54, "white")
        self._append_log("Benchmark started.", "green")

        self._log_queue = queue.Queue()
        self._engine    = BitaxeBenchmark(cfg, self._log_queue)

        self._benchmark_thread = threading.Thread(
            target=self._engine.run, daemon=True
        )
        self._benchmark_thread.start()

    def _stop(self):
        if self._engine:
            self._engine.stop_event.set()
            self._append_log("Stop requested — finishing current sample…", "yellow")
            self._stop_btn.config(state="disabled")

    def _on_benchmark_done(self):
        self._start_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        self._append_log("─ Benchmark finished ─", "green")

    # -------------------------------------------- open analysis window ---
    def _open_analysis(self):
        AnalysisWindow(self)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = App()
    app.mainloop()

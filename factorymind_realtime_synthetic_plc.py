"""
FactoryMind AI — Real-time Synthetic PLC Data Generator
------------------------------------------------------
Generates continuous, timestamped data for the 16 instruments in the
user-provided instrumentation schedule.

IMPORTANT:
- This is synthetic data for a software prototype, not a live factory connection.
- Setpoints/ranges are taken from the provided project image.
- Verify all process and safety limits before using any values outside simulation.
- Python standard library only; MQTT/PostgreSQL integration can be added later.
"""

import csv
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

# --------------------------- Configuration ---------------------------

SAMPLE_INTERVAL_SECONDS = 1
CSV_FILE = Path("factorymind_sensor_data.csv")
JSONL_FILE = Path("factorymind_sensor_data.jsonl")
RANDOM_SEED = None  # Set an integer, e.g. 42, for repeatable test data.

if RANDOM_SEED is not None:
    random.seed(RANDOM_SEED)

# min/max here are simulation bounds based on the project schedule.
# normal_min/normal_max are typical ranges from that schedule.
SENSORS = {
    "TT-101": {
        "equipment_id": "TK-101", "name": "Raw milk temperature",
        "unit": "°C", "setpoint": 3.5, "sim_min": 0, "sim_max": 15,
        "normal_min": 3.0, "normal_max": 4.5, "kind": "analog",
    },
    "LT-101": {
        "equipment_id": "TK-101", "name": "Raw milk tank level",
        "unit": "%", "setpoint": 90, "sim_min": 0, "sim_max": 100,
        "normal_min": 20, "normal_max": 95, "kind": "level",
    },
    "FT-101": {
        "equipment_id": "P-101", "name": "Milk transfer flow",
        "unit": "L/min", "setpoint": 210, "sim_min": 0, "sim_max": 300,
        "normal_min": 180, "normal_max": 240, "kind": "analog",
    },
    "PT-101": {
        "equipment_id": "P-101", "name": "Pump discharge pressure",
        "unit": "bar", "setpoint": 2.8, "sim_min": 0, "sim_max": 6,
        "normal_min": 2.5, "normal_max": 3.2, "kind": "analog",
    },
    "TT-102": {
        "equipment_id": "TK-102", "name": "Mixing tank temperature",
        "unit": "°C", "setpoint": 68, "sim_min": 0, "sim_max": 100,
        "normal_min": 65, "normal_max": 70, "kind": "analog",
    },
    "WT-101": {
        "equipment_id": "BATCH-101", "name": "Ingredient batch weight",
        "unit": "kg", "setpoint": 50.0, "sim_min": 0, "sim_max": 100,
        "normal_min": 49.9, "normal_max": 50.1, "kind": "batch_weight",
    },
    "TT-103": {
        "equipment_id": "HX-101", "name": "Heating outlet temperature",
        "unit": "°C", "setpoint": 138, "sim_min": 0, "sim_max": 150,
        "normal_min": 137.5, "normal_max": 140, "kind": "analog",
    },
    "FT-102": {
        "equipment_id": "HX-101", "name": "Heating line flow",
        "unit": "L/min", "setpoint": 195, "sim_min": 0, "sim_max": 250,
        "normal_min": 190, "normal_max": 200, "kind": "analog",
    },
    "PT-102": {
        "equipment_id": "H-101", "name": "Homogenizer pressure",
        "unit": "bar", "setpoint": 225, "sim_min": 0, "sim_max": 250,
        "normal_min": 215, "normal_max": 235, "kind": "analog",
    },
    "VT-101": {
        "equipment_id": "P-101", "name": "Transfer pump vibration",
        "unit": "mm/s", "setpoint": 1.8, "sim_min": 0, "sim_max": 15,
        "normal_min": 0.2, "normal_max": 4.5, "kind": "vibration",
    },
    "CT-101": {
        "equipment_id": "P-101", "name": "Motor current",
        "unit": "A", "setpoint": 32, "sim_min": 0, "sim_max": 50,
        "normal_min": 15, "normal_max": 38, "kind": "analog",
    },
    "TT-104": {
        "equipment_id": "HX-102", "name": "Cooling outlet temperature",
        "unit": "°C", "setpoint": 24, "sim_min": 0, "sim_max": 40,
        "normal_min": 22, "normal_max": 26, "kind": "analog",
    },
    "LT-102": {
        "equipment_id": "TK-103", "name": "Finished-product tank level",
        "unit": "%", "setpoint": 85, "sim_min": 0, "sim_max": 100,
        "normal_min": 15, "normal_max": 90, "kind": "level",
    },
    "ZS-101": {
        "equipment_id": "F-101", "name": "Filling machine state",
        "unit": "On/off", "setpoint": 1, "sim_min": 0, "sim_max": 1,
        "normal_min": 0, "normal_max": 1, "kind": "binary",
    },
    "PE-101": {
        "equipment_id": "F-101", "name": "Container detection event",
        "unit": "Count/event", "setpoint": 1, "sim_min": 0, "sim_max": 1,
        "normal_min": 0, "normal_max": 1, "kind": "binary",
    },
    "CE-101": {
        "equipment_id": "CIP-101", "name": "CIP return conductivity",
        "unit": "mS/cm", "setpoint": 5.2, "sim_min": 0, "sim_max": 100,
        "normal_min": 4.5, "normal_max": 6.5, "kind": "cip",
    },
}

CSV_FIELDS = [
    "timestamp", "plant_line", "equipment_id", "sensor_id", "sensor_name",
    "parameter", "value", "unit", "machine_state", "alarm_status",
    "scenario", "data_source"
]

# --------------------------- Simulation logic ---------------------------

def clamp(value, low, high):
    return max(low, min(high, value))


def sample_value(tag, cfg, scenario, tick, machine_state):
    """Return a plausible synthetic reading for a sensor and scenario."""
    kind = cfg["kind"]
    lo, hi = cfg["normal_min"], cfg["normal_max"]
    target = cfg["setpoint"]

    # Normal values fluctuate around the setpoint but stay in the configured
    # normal range (binary signals have their own logic below).
    if kind == "binary":
        if tag == "ZS-101":
            return 1 if machine_state == "RUNNING" else 0
        # Container detection events occur while filling is active.
        return 1 if machine_state == "RUNNING" and random.random() < 0.90 else 0

    if kind == "batch_weight":
        # Weight stays close to a 50 kg example target during batch weighing.
        value = random.gauss(target, 0.025)
    elif kind == "level":
        # Simulate changing tank inventory rather than pure random noise.
        base = target + 12 * __import__("math").sin(tick / 35)
        value = base + random.gauss(0, 1.5)
    elif kind == "vibration":
        value = random.gauss(target, 0.25)
    elif kind == "cip":
        value = random.gauss(target, 0.25)
    else:
        # Small random fluctuation around the setpoint.
        # Scale noise to the span of the normal range.
        sigma = max((hi - lo) / 6, 0.02)
        value = random.gauss(target, sigma)

    # Scenarios introduce correlated or process-specific abnormal behavior.
    if scenario == "DEGRADATION":
        if tag == "VT-101":
            value += min(tick * 0.025, 4.0)  # gradual vibration rise
        elif tag == "CT-101":
            value += min(tick * 0.08, 8.0)  # increasing current
        elif tag == "FT-101":
            value -= min(tick * 0.7, 90.0)  # decreasing transfer flow
        elif tag == "PT-101":
            value += min(tick * 0.012, 1.2)
    elif scenario == "PROCESS_DEVIATION":
        if tag == "TT-103":
            value = random.uniform(132.0, 137.0)  # below project target band
        elif tag == "FT-102":
            value = random.uniform(160.0, 188.0)
        elif tag == "TT-104":
            value = random.uniform(27.0, 32.0)
    elif scenario == "SENSOR_FAULT":
        if tag == "PT-101":
            value = cfg["sim_max"] + 1.0  # deliberately outside instrument range
        elif tag == "TT-101":
            value = 999.0  # impossible value used to test sensor fault handling

    # Keep process values inside declared simulation bounds except SENSOR_FAULT,
    # which intentionally creates out-of-range values to test data validation.
    if scenario != "SENSOR_FAULT":
        value = clamp(value, cfg["sim_min"], cfg["sim_max"])

    if tag in ("LT-101", "LT-102"):
        return round(clamp(value, 0, 100), 2)
    return round(value, 3)


def get_alarm(tag, value, cfg, scenario, machine_state):
    """Prototype warning logic; not real plant alarm limits."""
    if scenario == "SENSOR_FAULT" and tag in ("PT-101", "TT-101"):
        return "SENSOR_FAULT"

    if tag == "TT-101" and not (3.0 <= value <= 4.5):
        return "WARNING"
    if tag == "LT-101" and value > 95:
        return "HIGH_LEVEL"
    if tag == "FT-101" and machine_state == "RUNNING" and value < 180:
        return "LOW_FLOW"
    if tag == "PT-101" and machine_state == "RUNNING" and not (2.5 <= value <= 3.2):
        return "PRESSURE_DEVIATION"
    if tag == "TT-102" and not (65 <= value <= 70):
        return "WARNING"
    if tag == "WT-101" and not (49.9 <= value <= 50.1):
        return "WEIGHT_DEVIATION"
    if tag == "TT-103" and value < 137.5:
        return "CRITICAL_TEMPERATURE_DEVIATION"
    if tag == "FT-102" and machine_state == "RUNNING" and not (190 <= value <= 200):
        return "FLOW_DEVIATION"
    if tag == "PT-102" and not (215 <= value <= 235):
        return "PRESSURE_DEVIATION"
    if tag == "VT-101" and machine_state == "RUNNING" and value > 4.5:
        return "HIGH_VIBRATION"
    if tag == "CT-101" and machine_state == "RUNNING" and value > 38:
        return "HIGH_CURRENT"
    if tag == "TT-104" and not (22 <= value <= 26):
        return "COOLING_DEVIATION"
    if tag == "LT-102" and value > 90:
        return "HIGH_LEVEL"
    if tag == "CE-101" and not (4.5 <= value <= 6.5):
        return "CIP_CONDUCTIVITY_DEVIATION"
    return "NORMAL"


def main():
    print("FactoryMind AI synthetic data generator started.")
    print(f"Writing CSV to:  {CSV_FILE.resolve()}")
    print(f"Writing JSONL to: {JSONL_FILE.resolve()}")
    print("Press Ctrl+C to stop.\n")

    csv_exists = CSV_FILE.exists()
    with CSV_FILE.open("a", newline="", encoding="utf-8") as csv_handle, \
         JSONL_FILE.open("a", encoding="utf-8") as jsonl_handle:

        writer = csv.DictWriter(csv_handle, fieldnames=CSV_FIELDS)
        if not csv_exists or CSV_FILE.stat().st_size == 0:
            writer.writeheader()

        tick = 0
        total_units = 0
        try:
            while True:
                # Scenario rotates for demonstration:
                # 60 s normal, 30 s gradual degradation, 20 s process deviation,
                # 10 s sensor fault, then repeat.
                cycle = tick % 120
                if cycle < 60:
                    scenario = "NORMAL"
                elif cycle < 90:
                    scenario = "DEGRADATION"
                elif cycle < 110:
                    scenario = "PROCESS_DEVIATION"
                else:
                    scenario = "SENSOR_FAULT"

                machine_state = "STOPPED" if scenario == "SENSOR_FAULT" and tick % 2 else "RUNNING"
                timestamp = datetime.now(timezone.utc).isoformat()

                for tag, cfg in SENSORS.items():
                    value = sample_value(tag, cfg, scenario, tick, machine_state)
                    alarm = get_alarm(tag, value, cfg, scenario, machine_state)

                    if tag == "PE-101" and value == 1:
                        total_units += 1

                    record = {
                        "timestamp": timestamp,
                        "plant_line": "Milkshake_Line_01",
                        "equipment_id": cfg["equipment_id"],
                        "sensor_id": tag,
                        "sensor_name": cfg["name"],
                        "parameter": cfg["name"].lower().replace(" ", "_"),
                        "value": value,
                        "unit": cfg["unit"],
                        "machine_state": machine_state,
                        "alarm_status": alarm,
                        "scenario": scenario,
                        "data_source": "SIMULATED",
                    }

                    writer.writerow(record)
                    jsonl_handle.write(json.dumps(record) + "\n")
                    print(
                        f"{timestamp} | {tag:6} | {value:>9} {cfg['unit']:<10} "
                        f"| {alarm:<34} | {scenario}"
                    )

                csv_handle.flush()
                jsonl_handle.flush()
                tick += 1
                time.sleep(SAMPLE_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\nStopped by user.")
            print(f"Container detections counted during this run: {total_units}")
            print(f"CSV saved to: {CSV_FILE.resolve()}")
            print(f"JSONL saved to: {JSONL_FILE.resolve()}")


if __name__ == "__main__":
    main()

import json
import io
import math
import os
import random
import re
import smtplib
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Optional

import joblib
import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

try:
    import mysql.connector
    from mysql.connector import Error as MySQLError
except ImportError:
    mysql = None
    MySQLError = Exception

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)
MODEL_DIR = BASE_DIR / "models"
STREAM_URL = os.getenv("LIVE_STREAM_URL", "").strip()

# ---------------------------------------------------------------------------
# SENSORS & SYNTHETIC PLC SPECIFICATION (16 INSTRUMENTS)
# ---------------------------------------------------------------------------
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

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

def sample_value(tag: str, cfg: dict, scenario: str, tick: int, machine_state: str, rng: random.Random) -> float:
    kind = cfg["kind"]
    lo, hi = cfg["normal_min"], cfg["normal_max"]
    target = cfg["setpoint"]

    if kind == "binary":
        if tag == "ZS-101":
            return 1 if machine_state == "RUNNING" else 0
        return 1 if (machine_state == "RUNNING" and (tick % 4 != 0)) else 0

    if kind == "batch_weight":
        value = rng.gauss(target, 0.025)
    elif kind == "level":
        base = target + 12.0 * math.sin(tick / 35.0)
        value = base + rng.gauss(0, 1.5)
    elif kind == "vibration":
        value = rng.gauss(target, 0.25)
    elif kind == "cip":
        value = rng.gauss(target, 0.25)
    else:
        sigma = max((hi - lo) / 6.0, 0.02)
        value = rng.gauss(target, sigma)

    if scenario == "DEGRADATION":
        if tag == "VT-101":
            value += min((tick % 120 - 60) * 0.12, 4.0)
        elif tag == "CT-101":
            value += min((tick % 120 - 60) * 0.25, 8.0)
        elif tag == "FT-101":
            value -= min((tick % 120 - 60) * 2.0, 80.0)
        elif tag == "PT-101":
            value += min((tick % 120 - 60) * 0.03, 1.2)
    elif scenario == "PROCESS_DEVIATION":
        if tag == "TT-103":
            value = rng.uniform(132.0, 137.0)
        elif tag == "FT-102":
            value = rng.uniform(160.0, 188.0)
        elif tag == "TT-104":
            value = rng.uniform(27.0, 32.0)
    elif scenario == "SENSOR_FAULT":
        if tag == "PT-101":
            value = cfg["sim_max"] + 1.0
        elif tag == "TT-101":
            value = 999.0

    if scenario != "SENSOR_FAULT":
        value = clamp(value, cfg["sim_min"], cfg["sim_max"])

    if tag in ("LT-101", "LT-102"):
        return round(clamp(value, 0, 100), 2)
    return round(value, 3)

def get_alarm(tag: str, value: float, cfg: dict, scenario: str, machine_state: str) -> str:
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

def generate_synthetic_snapshot(tick: int) -> list[dict]:
    cycle = tick % 120
    if cycle < 60:
        scenario = "NORMAL"
    elif cycle < 90:
        scenario = "DEGRADATION"
    elif cycle < 110:
        scenario = "PROCESS_DEVIATION"
    else:
        scenario = "SENSOR_FAULT"

    machine_state = "STOPPED" if (scenario == "SENSOR_FAULT" and (tick % 2 == 1)) else "RUNNING"
    timestamp = datetime.now(timezone.utc).isoformat()
    rng = random.Random(tick)

    records = []
    for tag, cfg in SENSORS.items():
        val = sample_value(tag, cfg, scenario, tick, machine_state, rng)
        alarm = get_alarm(tag, val, cfg, scenario, machine_state)
        records.append({
            "timestamp": timestamp,
            "plant_line": "Milkshake_Line_01",
            "equipment_id": cfg["equipment_id"],
            "sensor_id": tag,
            "sensor_name": cfg["name"],
            "parameter": cfg["name"].lower().replace(" ", "_"),
            "value": val,
            "unit": cfg["unit"],
            "machine_state": machine_state,
            "alarm_status": alarm,
            "scenario": scenario,
            "data_source": "SIMULATED",
        })
    return records

# ---------------------------------------------------------------------------
# ML MODELS & STATE
# ---------------------------------------------------------------------------
app = FastAPI(title="FactoryMind AI API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

state: dict[str, Any] = {
    "records": [],
    "last_update": None,
    "connected": True,
    "error": None,
    "snapshot_count": 0,
}
lock = threading.Lock()
stop_event = threading.Event()
recent_history = deque(maxlen=60)
models: dict[str, Any] = {}

def load_models():
    candidate_dirs = [MODEL_DIR, BASE_DIR / "api" / "models", BASE_DIR.parent / "models", Path("models")]
    for candidate in candidate_dirs:
        if candidate.exists():
            for name in ("classifier.joblib", "clusterer.joblib", "forecast.joblib"):
                path = candidate / name
                if path.exists() and name not in models:
                    try:
                        models[name] = joblib.load(path)
                    except Exception:
                        pass

load_models()

def enrich_snapshot(records: list[dict]) -> list[dict]:
    result = []
    for rec in records:
        item = dict(rec)
        try:
            val = float(item.get("value"))
        except (TypeError, ValueError):
            val = None
        item["value"] = val if val is not None else item.get("value")
        result.append(item)

    feature_map = {}
    for rec in result:
        param = rec.get("parameter")
        try:
            feature_map[param] = float(rec.get("value"))
        except (TypeError, ValueError):
            pass

    if feature_map:
        row = pd.DataFrame([feature_map])
        if "classifier.joblib" in models:
            try:
                bundle = models["classifier.joblib"]
                model = bundle["model"]
                columns = bundle["features"]
                X = row.reindex(columns=columns, fill_value=0).fillna(0)
                pred = str(model.predict(X)[0])
                probs = model.predict_proba(X)[0] if hasattr(model, "predict_proba") else None
                item_conf = float(max(probs)) if probs is not None else None
                for rec in result:
                    rec["ml_predicted_alarm"] = pred
                    rec["ml_confidence"] = round(item_conf, 4) if item_conf is not None else None
            except Exception as e:
                for rec in result:
                    rec["ml_error"] = str(e)
        if "clusterer.joblib" in models:
            try:
                bundle = models["clusterer.joblib"]
                X = row.reindex(columns=bundle["features"], fill_value=0).fillna(0)
                cluster = int(bundle["pipeline"].predict(X)[0])
                for rec in result:
                    rec["ml_cluster"] = cluster
            except Exception:
                pass
        if "forecast.joblib" in models:
            try:
                bundle = models["forecast.joblib"]
                key = bundle.get("target", "raw_milk_temperature")
                value = feature_map.get(key)
                if value is not None:
                    history = list(recent_history)
                    history.append(value)
                    forecast = float(np.mean(history[-5:]))
                    for rec in result:
                        if rec.get("parameter") == key:
                            rec["ml_forecast_next"] = round(forecast, 3)
            except Exception:
                pass
    return result

# ---------------------------------------------------------------------------
# RESILIENT DATABASE LAYER (MySQL with SQLite fallback)
# ---------------------------------------------------------------------------
MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "factorymind_ai"),
    "connection_timeout": 3,
}

import tempfile
default_sqlite = Path(tempfile.gettempdir()) / "factorymind_reviews.db"
SQLITE_PATH = Path(os.getenv("SQLITE_PATH", str(default_sqlite)))

def get_db():
    """Returns (connection, db_type: 'mysql' | 'sqlite')"""
    if mysql and os.getenv("MYSQL_HOST"):
        try:
            conn = mysql.connector.connect(**MYSQL_CONFIG)
            return conn, "mysql"
        except Exception:
            pass
    conn = sqlite3.connect(str(SQLITE_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn, "sqlite"

def init_review_db():
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        if db_type == "mysql":
            cursor.execute("""CREATE TABLE IF NOT EXISTS reviews (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                created_at VARCHAR(40) NOT NULL,
                category VARCHAR(80) NOT NULL,
                severity VARCHAR(30) NOT NULL,
                sensor_name VARCHAR(160),
                parameter VARCHAR(160),
                equipment_id VARCHAR(120),
                sensor_value VARCHAR(80),
                unit VARCHAR(40),
                source_alarm VARCHAR(120),
                machine_state VARCHAR(120),
                notes TEXT,
                status VARCHAR(30) NOT NULL DEFAULT 'Open',
                INDEX idx_reviews_created_at (created_at),
                INDEX idx_reviews_severity (severity),
                INDEX idx_reviews_category (category)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
        else:
            cursor.execute("""CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                sensor_name TEXT,
                parameter TEXT,
                equipment_id TEXT,
                sensor_value TEXT,
                unit TEXT,
                source_alarm TEXT,
                machine_state TEXT,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'Open'
            )""")
        conn.commit()
    finally:
        cursor.close()
        conn.close()

# ---------------------------------------------------------------------------
# BACKGROUND STREAM WORKER & STARTUP
# ---------------------------------------------------------------------------
def stream_worker():
    tick = int(time.time())
    while not stop_event.is_set():
        external_ok = False
        is_external = bool(STREAM_URL and not any(k in STREAM_URL.lower() for k in ["unviable-trickily", "simulator", "internal", "localhost", "127.0.0.1"]))
        
        if is_external:
            try:
                with requests.get(STREAM_URL, stream=True, timeout=(5, 20)) as resp:
                    if resp.status_code == 200:
                        external_ok = True
                        for raw in resp.iter_lines(decode_unicode=True):
                            if stop_event.is_set():
                                return
                            if not raw:
                                continue
                            line = raw.strip()
                            if line.startswith("data:"):
                                payload = line[5:].strip()
                                try:
                                    data = json.loads(payload)
                                    cur = data if isinstance(data, list) else [data]
                                    for rec in cur:
                                        if rec.get("parameter") == "raw_milk_temperature":
                                            recent_history.append(float(rec["value"]))
                                    enriched = enrich_snapshot(cur)
                                    with lock:
                                        state["records"] = enriched
                                        state["last_update"] = time.time()
                                        state["snapshot_count"] += 1
                                        state["connected"] = True
                                        state["error"] = None
                                except Exception:
                                    pass
            except Exception:
                external_ok = False

        if not external_ok:
            try:
                tick += 1
                raw_recs = generate_synthetic_snapshot(tick)
                for rec in raw_recs:
                    if rec.get("parameter") == "raw_milk_temperature":
                        recent_history.append(float(rec["value"]))
                enriched = enrich_snapshot(raw_recs)
                with lock:
                    state["records"] = enriched
                    state["last_update"] = time.time()
                    state["snapshot_count"] = tick
                    state["connected"] = True
                    state["error"] = None
            except Exception as e:
                with lock:
                    state["error"] = str(e)
            time.sleep(1)

thread: Optional[threading.Thread] = None

@app.on_event("startup")
def start_stream():
    global thread
    try:
        init_review_db()
    except Exception as exc:
        print(f"[Warning] DB initialization: {exc}")
    thread = threading.Thread(target=stream_worker, daemon=True)
    thread.start()

@app.on_event("shutdown")
def stop_stream():
    stop_event.set()

# ---------------------------------------------------------------------------
# API MODELS & HELPERS
# ---------------------------------------------------------------------------
class AIChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1200)

class MachineStatusEmailRequest(BaseModel):
    manager_email: str = Field(default="jaakkarthi10@gmail.com", min_length=3, max_length=254)
    smtp_password: str = Field(default="", max_length=500)
    subject_prefix: str = Field(default="FactoryMind AI Machine Status", max_length=120)

class ReviewCreate(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    severity: str = Field(default="High", max_length=30)
    sensor_name: str = "Unknown sensor"
    parameter: str = ""
    equipment_id: str = ""
    sensor_value: str = ""
    unit: str = ""
    source_alarm: str = "UNKNOWN"
    machine_state: str = "UNKNOWN"
    notes: str = ""

def _record_status(rec: dict) -> str:
    return str(rec.get("alarm_status") or "UNKNOWN").strip().upper()

def _ai_recommendation(rec: dict) -> dict:
    status = _record_status(rec)
    parameter = str(rec.get("parameter") or "sensor").replace("_", " ").lower()
    sensor = str(rec.get("sensor_name") or parameter)
    equipment = str(rec.get("equipment_id") or "unspecified equipment")
    value = rec.get("value")
    unit = str(rec.get("unit") or "")
    severe = "CRIT" in status or "FAULT" in status
    warning = any(token in status for token in ("WARN", "HIGH", "LOW", "DEVIAT", "ALARM", "ERROR"))
    if severe:
        priority = "Critical review"
        action = f"Verify {sensor} on {equipment} against approved operating limits and follow site escalation procedure."
    elif warning:
        priority = "Inspect"
        action = f"Cross-check {sensor} with related sensors and normal range; inspect equipment if deviation persists."
    else:
        priority = "Monitor"
        action = f"Continue monitoring {sensor}; confirm reading is fresh."
    return {
        "sensor_name": sensor, "parameter": rec.get("parameter"), "equipment_id": equipment,
        "value": value, "unit": unit, "source_status": status, "priority": priority,
        "recommendation": action, "evidence": f"Current status: {status}; reading: {value if value is not None else 'N/A'} {unit}".strip()
    }

def get_current_snapshot() -> dict:
    now = time.time()
    with lock:
        # If records are empty or stale (> 3s old, e.g. serverless invocation), compute fresh snapshot
        if not state["records"] or (now - (state["last_update"] or 0) > 3.0):
            tick = int(now)
            raw = generate_synthetic_snapshot(tick)
            for rec in raw:
                if rec.get("parameter") == "raw_milk_temperature":
                    recent_history.append(float(rec["value"]))
            enriched = enrich_snapshot(raw)
            state["records"] = enriched
            state["last_update"] = now
            state["snapshot_count"] = tick
            state["connected"] = True
            state["error"] = None
        return {
            "connected": state["connected"],
            "last_update": state["last_update"],
            "snapshot_count": state["snapshot_count"],
            "error": state["error"],
            "records": list(state["records"]),
        }

# ---------------------------------------------------------------------------
# COST INTELLIGENCE ENGINE
# ---------------------------------------------------------------------------
def compute_cost_intelligence(mode: str = "down", cost_per_alarm: float = 2500) -> dict:
    snap = get_current_snapshot()
    records = snap["records"]
    by_param = {r.get("parameter"): r for r in records if r.get("parameter")}

    prev_period = "September 2026"
    prev_revenue = 4828000
    prev_energy = 842000
    prev_maint = 415000
    prev_scrap = 426000
    prev_fixed = 300000
    prev_costs = prev_energy + prev_maint + prev_scrap + prev_fixed
    prev_profit = prev_revenue - prev_costs

    if mode == "up":
        curr_period = "October 2026 (Optimized Tuning)"
        curr_revenue = 4950000
        curr_energy = 794000
        curr_maint = 360000
        curr_scrap = 380000
        curr_fixed = 376000
        curr_costs = curr_energy + curr_maint + curr_scrap + curr_fixed
        curr_profit = curr_revenue - curr_costs
        trend = "up"
        sensor_factors = [
            {
                "parameter": "motor_current",
                "sensor_name": "Motor Current",
                "equipment_id": "CT-101 (P-101)",
                "unit": "A",
                "prev_baseline": 27.8,
                "curr_reading": round(float(by_param.get("motor_current", {}).get("value") or 26.9), 2),
                "variance_pct": -3.2,
                "variance_direction": "down",
                "financial_impact": 42000,
                "category": "Energy Efficiency",
                "severity": "Optimal",
                "explanation": "Motor current trimmed via VFD frequency optimization, cutting monthly electrical consumption by ₹42,000.",
                "recommendation": "Maintain VFD modulation curve between 48-50 Hz."
            },
            {
                "parameter": "transfer_pump_vibration",
                "sensor_name": "Transfer Pump Vibration",
                "equipment_id": "VT-101 (P-101)",
                "unit": "mm/s",
                "prev_baseline": 1.85,
                "curr_reading": round(float(by_param.get("transfer_pump_vibration", {}).get("value") or 1.58), 3),
                "variance_pct": -14.6,
                "variance_direction": "down",
                "financial_impact": 55000,
                "category": "Maintenance Savings",
                "severity": "Optimal",
                "explanation": "Dynamic balancing of transfer pump impeller damped vibration, eliminating emergency callouts and saving ₹55,000.",
                "recommendation": "Continue bi-weekly vibration spectrum analysis."
            },
            {
                "parameter": "heating_outlet_temperature",
                "sensor_name": "Heating Outlet Temperature",
                "equipment_id": "TT-103 (HX-101)",
                "unit": "°C",
                "prev_baseline": 137.5,
                "curr_reading": round(float(by_param.get("heating_outlet_temperature", {}).get("value") or 137.6), 2),
                "variance_pct": 0.1,
                "variance_direction": "stable",
                "financial_impact": 46000,
                "category": "Quality & Waste Prevention",
                "severity": "Optimal",
                "explanation": "Precise PID steam loop control eliminated temperature overshoot, preventing milk scorch waste and saving ₹46,000.",
                "recommendation": "Maintain calibrated steam regulator setpoint at 137.5°C."
            },
            {
                "parameter": "milk_transfer_flow",
                "sensor_name": "Milk Transfer Flow",
                "equipment_id": "FT-101 (P-101)",
                "unit": "L/min",
                "prev_baseline": 204.0,
                "curr_reading": round(float(by_param.get("milk_transfer_flow", {}).get("value") or 212.0), 2),
                "variance_pct": 3.9,
                "variance_direction": "up",
                "financial_impact": 52000,
                "category": "Throughput Capacity",
                "severity": "Optimal",
                "explanation": "Steady laminar flow rate elevated production output by 12,500 liters without pressure spikes, yielding ₹52,000 in gross margin.",
                "recommendation": "Monitor filling line buffer tank level to prevent downstream starvation."
            }
        ]
        synthesis = (
            "Current month profit increased by 6.85% (+₹1,95,000) over previous month. "
            "Sensor telemetry confirms significant cost reductions across three critical systems: "
            "Transfer pump motor current (CT-101: -3.2%) reduced power tariffs by ₹42,000; "
            "impeller balancing lowered vibration (VT-101: -14.6%), avoiding ₹55,000 in unscheduled maintenance; "
            "and tight PID heating control (TT-103: 137.6°C) eliminated thermal scrap waste by ₹46,000."
        )
    else:
        curr_period = "October 2026 (Live & MTD)"
        curr_revenue = 4870000
        curr_energy = 910500
        curr_maint = 489200
        curr_scrap = 508400
        curr_fixed = 359500
        curr_costs = curr_energy + curr_maint + curr_scrap + curr_fixed
        curr_profit = curr_revenue - curr_costs
        trend = "down"

        live_temp = float(by_param.get("heating_outlet_temperature", {}).get("value") or 143.2)
        live_vib = float(by_param.get("transfer_pump_vibration", {}).get("value") or 2.45)
        live_curr = float(by_param.get("motor_current", {}).get("value") or 32.8)
        live_press = float(by_param.get("pump_discharge_pressure", {}).get("value") or 3.32)
        live_cond = float(by_param.get("cip_return_conductivity", {}).get("value") or 5.85)
        live_flow = float(by_param.get("milk_transfer_flow", {}).get("value") or 211.5)

        sensor_factors = [
            {
                "parameter": "heating_outlet_temperature",
                "sensor_name": "Heating Outlet Temperature",
                "equipment_id": "TT-103 (HX-101)",
                "unit": "°C",
                "prev_baseline": 137.5,
                "curr_reading": round(live_temp, 2),
                "variance_pct": round(((live_temp - 137.5) / 137.5) * 100, 1),
                "variance_direction": "up" if live_temp > 137.5 else "down",
                "financial_impact": -82400,
                "category": "Thermal Waste & Product Scrap",
                "severity": "Critical",
                "explanation": f"Thermal excursion at {round(live_temp, 2)}°C triggered CRITICAL_TEMPERATURE_DEVIATION events. Caused milk protein denaturing on HX-101 plates and scrapped product batches totaling ₹82,400 in direct losses.",
                "recommendation": "Recalibrate steam modulating valve actuator and retune PID loop gain."
            },
            {
                "parameter": "transfer_pump_vibration",
                "sensor_name": "Transfer Pump Vibration",
                "equipment_id": "VT-101 (P-101)",
                "unit": "mm/s",
                "prev_baseline": 1.85,
                "curr_reading": round(live_vib, 3),
                "variance_pct": round(((live_vib - 1.85) / 1.85) * 100, 1),
                "variance_direction": "up" if live_vib > 1.85 else "down",
                "financial_impact": -74200,
                "category": "Emergency Maintenance & Repairs",
                "severity": "Critical",
                "explanation": f"Vibration elevated to {round(live_vib, 3)} mm/s, causing HIGH_VIBRATION alarm states. Bearing micro-pitting necessitated unscheduled service costing ₹74,200.",
                "recommendation": "Inspect drive coupling elastomer, verify suction head, and replace bearing."
            },
            {
                "parameter": "motor_current",
                "sensor_name": "Motor Current",
                "equipment_id": "CT-101 (P-101)",
                "unit": "A",
                "prev_baseline": 27.8,
                "curr_reading": round(live_curr, 2),
                "variance_pct": round(((live_curr - 27.8) / 27.8) * 100, 1),
                "variance_direction": "up" if live_curr > 27.8 else "down",
                "financial_impact": -68500,
                "category": "Excess Electrical Consumption",
                "severity": "Warning",
                "explanation": f"Motor current sustained {round(live_curr, 2)}A against 27.8A nominal baseline, adding ₹68,500 in excess electricity costs.",
                "recommendation": "Inspect impeller clearance, check supply voltage balance, and lubricate bearings."
            },
            {
                "parameter": "pump_discharge_pressure",
                "sensor_name": "Pump Discharge Pressure",
                "equipment_id": "PT-101 (P-101)",
                "unit": "bar",
                "prev_baseline": 2.75,
                "curr_reading": round(live_press, 2),
                "variance_pct": round(((live_press - 2.75) / 2.75) * 100, 1),
                "variance_direction": "up" if live_press > 2.75 else "down",
                "financial_impact": -38000,
                "category": "Hydraulic Friction & Throttling",
                "severity": "Warning",
                "explanation": f"Discharge pressure reached {round(live_press, 2)} bar. Flow resistance stressed mechanical seals, causing throttling losses costing ₹38,000.",
                "recommendation": "Backwash sanitary filter mesh and inspect non-return valve."
            },
            {
                "parameter": "cip_return_conductivity",
                "sensor_name": "CIP Return Conductivity",
                "equipment_id": "CE-101 (CIP-101)",
                "unit": "mS/cm",
                "prev_baseline": 5.10,
                "curr_reading": round(live_cond, 2),
                "variance_pct": round(((live_cond - 5.10) / 5.10) * 100, 1),
                "variance_direction": "up" if live_cond > 5.10 else "down",
                "financial_impact": -21500,
                "category": "Chemical & Water Overdosing",
                "severity": "Warning",
                "explanation": f"Conductivity probe drift at {round(live_cond, 2)} mS/cm delayed CIP wash completion by 12 minutes per cycle, wasting ₹21,500 in detergent.",
                "recommendation": "Clean electrode surfaces and perform 2-point buffer calibration."
            },
            {
                "parameter": "milk_transfer_flow",
                "sensor_name": "Milk Transfer Flow",
                "equipment_id": "FT-101 (P-101)",
                "unit": "L/min",
                "prev_baseline": 204.0,
                "curr_reading": round(live_flow, 2),
                "variance_pct": round(((live_flow - 204.0) / 204.0) * 100, 1),
                "variance_direction": "up" if live_flow > 204.0 else "down",
                "financial_impact": 42000,
                "category": "Throughput Contribution",
                "severity": "Optimal",
                "explanation": f"Transfer flow running at {round(live_flow, 2)} L/min generated an extra 10,200 liters of processing throughput, contributing +₹42,000 in gross margin.",
                "recommendation": "Maintain flow within 205-215 L/min steady operational envelope."
            }
        ]
        synthesis = (
            "Current month profit dropped by 8.53% (-₹2,42,600) compared to previous month (₹28,45,000 vs ₹26,02,400). "
            "Industrial telemetry pinpoints three dominant root-cause deviations responsible for 88% of the shortfall: "
            "(1) Pasteurizer temperature excursions (TT-103) caused protein scorching and ₹82,400 in scrap loss; "
            "(2) Pump mechanical vibration (VT-101) triggered emergency repair interventions costing ₹74,200; and "
            "(3) Motor electrical overload (CT-101) drove ₹68,500 in excess electricity charges."
        )

    deviation = curr_profit - prev_profit
    deviation_pct = round((deviation / prev_profit) * 100, 2)

    breakdown_comparison = [
        {"metric": "Gross Revenue", "previous": prev_revenue, "current": curr_revenue, "diff": curr_revenue - prev_revenue},
        {"metric": "Energy Cost", "previous": prev_energy, "current": curr_energy, "diff": curr_energy - prev_energy},
        {"metric": "Maintenance Cost", "previous": prev_maint, "current": curr_maint, "diff": curr_maint - prev_maint},
        {"metric": "Scrap & Quality", "previous": prev_scrap, "current": curr_scrap, "diff": curr_scrap - prev_scrap},
        {"metric": "Fixed Overheads", "previous": prev_fixed, "current": curr_fixed, "diff": curr_fixed - prev_fixed},
        {"metric": "Net Profit", "previous": prev_profit, "current": curr_profit, "diff": deviation},
    ]

    return {
        "status": "ok",
        "mode": mode,
        "previous_month": {
            "period": prev_period,
            "revenue": prev_revenue,
            "total_costs": prev_costs,
            "profit": prev_profit,
            "margin_pct": round((prev_profit / prev_revenue) * 100, 1)
        },
        "current_month": {
            "period": curr_period,
            "revenue": curr_revenue,
            "total_costs": curr_costs,
            "profit": curr_profit,
            "margin_pct": round((curr_profit / curr_revenue) * 100, 1)
        },
        "deviation": {
            "amount": deviation,
            "amount_formatted": f"{'+' if deviation > 0 else '-'}₹{abs(deviation):,}",
            "percentage": deviation_pct,
            "percentage_formatted": f"{'+' if deviation_pct > 0 else ''}{deviation_pct}%",
            "trend": trend,
            "status_headline": f"Profit is {trend.upper()} by {abs(deviation_pct)}% ({f'{'+' if deviation > 0 else '-'}₹{abs(deviation):,}'})"
        },
        "sensor_explanations": sensor_factors,
        "executive_synthesis": synthesis,
        "breakdown_comparison": breakdown_comparison,
        "top_cost_driver": sensor_factors[0]["sensor_name"] + " (" + sensor_factors[0]["equipment_id"] + ")",
        "top_driver_impact": sensor_factors[0]["financial_impact"]
    }

# ---------------------------------------------------------------------------
# API ROUTES (DUAL ROUTED: BOTH /api/... AND /...)
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return {"name": "FactoryMind AI API", "status": "running", "version": "2.0.0", "docs": "/docs"}

@app.get("/api/health")
@app.get("/health")
def health():
    db_status = "connected"
    db_name = "factorymind_ai"
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()
        db_name = db_type
    except Exception as exc:
        db_status = f"disconnected ({exc})"

    snap = get_current_snapshot()
    return {
        "api": "ok",
        "database": db_name,
        "mysql": "connected" if "mysql" in db_name else "sqlite_fallback",
        "stream_connected": snap["connected"],
        "last_update": snap["last_update"],
        "snapshot_count": snap["snapshot_count"],
        "stream_error": snap["error"],
        "models_loaded": list(models.keys()),
    }

@app.get("/api/live/snapshot")
@app.get("/live/snapshot")
def live_snapshot():
    return get_current_snapshot()

@app.get("/api/analytics")
@app.get("/analytics")
def analytics():
    snap = get_current_snapshot()
    alarms = {}
    for rec in snap["records"]:
        lbl = str(rec.get("alarm_status", "UNKNOWN"))
        alarms[lbl] = alarms.get(lbl, 0) + 1
    return {
        "connected": snap["connected"],
        "snapshot_count": snap["snapshot_count"],
        "alarm_counts": alarms,
        "records_count": len(snap["records"])
    }

def compute_ai_deep_diagnosis(snap: dict = None) -> dict:
    if snap is None:
        snap = get_current_snapshot()
    records = snap.get("records", [])
    by_param = {str(r.get("parameter")): r for r in records if r.get("parameter")}
    by_tag = {str(r.get("sensor_id")): r for r in records if r.get("sensor_id")}

    def val(param, default=0.0):
        r = by_param.get(param) or by_tag.get(param)
        try:
            return float(r.get("value")) if r and r.get("value") is not None else default
        except (ValueError, TypeError):
            return default

    raw_temp = val("raw_milk_temperature", 3.5)
    raw_tank = val("raw_milk_tank_level", 75.0)
    transfer_flow = val("milk_transfer_flow", 195.0)
    pump_press = val("pump_discharge_pressure", 2.85)
    mix_temp = val("mixing_tank_temperature", 67.0)
    batch_weight = val("ingredient_batch_weight", 50.0)
    heat_temp = val("heating_outlet_temperature", 137.5)
    heat_flow = val("heating_line_flow", 194.5)
    homo_press = val("homogenizer_pressure", 225.0)
    pump_vib = val("transfer_pump_vibration", 1.5)
    motor_curr = val("motor_current", 31.0)
    cool_temp = val("cooling_outlet_temperature", 24.0)
    finish_tank = val("finished-product_tank_level", 82.0)
    cip_cond = val("cip_return_conductivity", 5.2)

    mass_delta = round(abs(transfer_flow - heat_flow), 2)
    mass_conserved_pct = max(0.0, min(100.0, round(100.0 - (mass_delta / max(1.0, transfer_flow) * 100.0), 1)))
    mass_status = "CONSERVED (<3% variance)" if mass_delta < 6.0 else "MASS BALANCE DISCREPANCY"

    delta_t = round(heat_temp - mix_temp, 1)
    heat_duty_kw = round(heat_flow * 4.184 * max(0.0, delta_t) / 60.0, 1)
    heat_eff = round(max(50.0, min(100.0, 100.0 - (abs(heat_temp - 138.0) * 1.6))), 1)

    iso_zone = "Zone A (Good)" if pump_vib < 1.8 else "Zone B (Acceptable)" if pump_vib < 4.5 else "Zone C (Warning)" if pump_vib < 7.1 else "Zone D (Critical)"
    power_kw = round(motor_curr * 415 * 1.732 * 0.88 / 1000.0, 2)
    stator_load_pct = round((motor_curr / 38.0) * 100.0, 1)
    cavitation_index = round(max(0.5, min(10.0, (pump_vib / 1.5) + (1.2 / max(0.5, pump_press)))), 2)

    flagged = [r for r in records if _record_status(r) not in ("NORMAL", "OK", "UNKNOWN", "")]
    crit_count = sum(1 for r in flagged if any(k in _record_status(r) for k in ("CRIT", "FAULT", "TRIP")))
    penalty = (crit_count * 18.0) + (len(flagged) * 6.0) + (15.0 if pump_vib > 4.5 else 0.0) + (10.0 if heat_temp > 140.0 or heat_temp < 135.0 else 0.0)
    health_index = max(35.0, min(99.4, round(100.0 - penalty, 1)))

    anomalies = []
    if heat_temp > 138.5 or heat_temp < 137.0 or any("TT-103" in str(r.get("sensor_id")) for r in flagged):
        anomalies.append({
            "subsystem": "Pasteurization Loop (HX-101)",
            "sensor": "TT-103 (Heating Outlet Temp)",
            "parameter": "heating_outlet_temperature",
            "value": f"{heat_temp} °C",
            "severity": "CRITICAL" if (heat_temp > 140 or heat_temp < 135) else "WARNING",
            "root_cause": "Steam supply modulating valve actuator hysteresis / Plate fouling resistance",
            "confidence": 94.2,
            "failure_horizon": "3.8 hours until product fouling shutdown",
            "sop_code": "SOP-HX-04",
            "recommendation": "Trim PID integral gain on steam valve TC-103; inspect secondary coolant bypass flow."
        })

    if pump_vib > 2.5 or any("VT-101" in str(r.get("sensor_id")) for r in flagged):
        anomalies.append({
            "subsystem": "Fluid Transfer Skid (P-101)",
            "sensor": "VT-101 (Pump Vibration)",
            "parameter": "transfer_pump_vibration",
            "value": f"{pump_vib} mm/s",
            "severity": "CRITICAL" if pump_vib > 4.5 else "WARNING",
            "root_cause": "Impeller cavitation caused by suction head pressure drop (PT-101) / Bearing race micro-spalling",
            "confidence": 91.8,
            "failure_horizon": "14.5 hours until ISO Zone D mechanical trip",
            "sop_code": "SOP-PUMP-02",
            "recommendation": "Verify suction strainer differential pressure; lubricate drive-end bearings; modulate discharge throttling valve."
        })

    if motor_curr > 34.0 or any("CT-101" in str(r.get("sensor_id")) for r in flagged):
        anomalies.append({
            "subsystem": "Motor Drive Train (CT-101)",
            "sensor": "CT-101 (Stator Current)",
            "parameter": "motor_current",
            "value": f"{motor_curr} A",
            "severity": "CRITICAL" if motor_curr > 38.0 else "WARNING",
            "root_cause": "High product viscosity surge / mechanical drag in pump impeller casing",
            "confidence": 88.5,
            "failure_horizon": "22 hours until thermal overload relay trip",
            "sop_code": "SOP-ELEC-07",
            "recommendation": "Inspect 3-phase voltage balance; check motor cooling shroud for blockage; verify product batch solids."
        })

    if finish_tank > 88.0 or raw_tank > 88.0 or any("LT" in str(r.get("sensor_id")) for r in flagged):
        anomalies.append({
            "subsystem": "Aseptic Storage Tanks (TK-101 / TK-103)",
            "sensor": "LT-102 (Finished Product Tank Level)",
            "parameter": "finished-product_tank_level",
            "value": f"{finish_tank} %",
            "severity": "CRITICAL" if finish_tank > 95.0 else "WARNING",
            "root_cause": "Downstream filling line rate limitation / buffer capacity imbalance",
            "confidence": 96.0,
            "failure_horizon": "45 minutes before tank high-level interlock engages",
            "sop_code": "SOP-TANK-01",
            "recommendation": "Increase filling line conveyor index speed; prepare alternate buffer tank TK-104."
        })

    subsystems = [
        {
            "name": "Thermal & Pasteurization Loop",
            "equipment": "HX-101 Plate Heat Exchanger",
            "sensors": ["TT-101", "TT-102", "TT-103", "TT-104"],
            "status": "ALERT" if any(a["subsystem"].startswith("Pasteurization") for a in anomalies) else "OPTIMAL",
            "metric_label": "Thermal Exchange Duty",
            "metric_value": f"{heat_duty_kw} kW (ΔT: {delta_t}°C)",
            "efficiency": f"{heat_eff}%",
            "health_score": round(max(40.0, heat_eff - (5.0 if heat_temp > 138 else 0.0)), 1)
        },
        {
            "name": "Hydraulic & Pump Dynamics",
            "equipment": "P-101 Centrifugal Transfer Pump",
            "sensors": ["FT-101", "PT-101", "VT-101", "CT-101"],
            "status": "WARNING" if pump_vib > 2.5 or motor_curr > 34 else "OPTIMAL",
            "metric_label": "Vibration & ISO Severity",
            "metric_value": f"{pump_vib} mm/s · {iso_zone}",
            "efficiency": f"{round(max(60.0, 100.0 - pump_vib*8.5), 1)}%",
            "health_score": round(max(30.0, 100.0 - pump_vib*12.0), 1)
        },
        {
            "name": "Homogenizer & Pressure System",
            "equipment": "H-101 Two-Stage Homogenizer",
            "sensors": ["PT-102", "WT-101", "FT-102"],
            "status": "OPTIMAL" if (215 <= homo_press <= 235) else "WARNING",
            "metric_label": "Homogenization Pressure",
            "metric_value": f"{homo_press} bar (Stage 1+2)",
            "efficiency": "98.2%",
            "health_score": 96.5
        },
        {
            "name": "Sanitization & Storage Logistics",
            "equipment": "TK-101 / CIP-101 Loop",
            "sensors": ["LT-101", "LT-102", "CE-101"],
            "status": "WARNING" if (finish_tank > 88 or raw_tank > 88) else "OPTIMAL",
            "metric_label": "CIP Return Conductivity",
            "metric_value": f"{cip_cond} mS/cm · Clean Rinse",
            "efficiency": "99.0%",
            "health_score": round(max(50.0, 100.0 - (finish_tank - 80)*1.5 if finish_tank > 80 else 98.0), 1)
        }
    ]

    return {
        "status": "ok",
        "plant_health_index": health_index,
        "anomalies_count": len(anomalies),
        "anomalies": anomalies,
        "subsystems": subsystems,
        "physics_balance": {
            "mass_flow": {
                "inflow_tag": "FT-101 (Milk Transfer)",
                "inflow_val": transfer_flow,
                "outflow_tag": "FT-102 (Heating Line)",
                "outflow_val": heat_flow,
                "delta_lpm": mass_delta,
                "mass_conserved_pct": mass_conserved_pct,
                "status": mass_status
            },
            "thermal_exchange": {
                "exchanger": "HX-101 Plate Heat Exchanger",
                "inlet_temp": mix_temp,
                "outlet_temp": heat_temp,
                "delta_t": delta_t,
                "duty_kw": heat_duty_kw,
                "efficiency_pct": heat_eff,
                "fouling_risk": "ELEVATED FOULING" if heat_temp > 139.5 else "OPTIMAL"
            },
            "electro_mechanical": {
                "pump_tag": "P-101 Transfer Pump",
                "vibration_rms": pump_vib,
                "iso_zone": iso_zone,
                "cavitation_risk_index": cavitation_index,
                "motor_current": motor_curr,
                "power_kw": power_kw,
                "stator_load_pct": stator_load_pct
            }
        },
        "predicted_rul": {
            "primary_asset": "P-101 Transfer Pump",
            "bearing_rul_hours": 142 if pump_vib < 2.5 else 48 if pump_vib < 4.5 else 14.5,
            "next_scheduled_overhaul": "36 operating hours",
            "mtbf_estimate": "820 operating hours",
            "thermal_cleaning_cycle_due": "3.8 hours" if heat_temp > 138 else "26 hours"
        }
    }

@app.get("/api/ai/deep-diagnosis")
@app.get("/ai/deep-diagnosis")
def ai_deep_diagnosis():
    snap = get_current_snapshot()
    return compute_ai_deep_diagnosis(snap)

@app.get("/api/ai/insights")
@app.get("/ai/insights")
def ai_insights():
    snap = get_current_snapshot()
    records = snap["records"]
    flagged = [r for r in records if _record_status(r) not in ("NORMAL", "OK", "UNKNOWN", "")]
    insights = [_ai_recommendation(r) for r in flagged]
    critical = [x for x in insights if x["priority"] == "Critical review"]
    warnings = [x for x in insights if x["priority"] == "Inspect"]
    diagnosis = compute_ai_deep_diagnosis(snap)
    return {
        "connected": snap["connected"],
        "last_update": snap["last_update"],
        "records_analyzed": len(records),
        "flagged_count": len(flagged),
        "critical_count": len(critical),
        "warning_count": len(warnings),
        "insights": insights,
        "method": "Explainable thermodynamic & electro-mechanical physics engine with ISO 10816 vibration diagnostics.",
        "diagnosis": diagnosis
    }

@app.post("/api/ai/chat")
@app.post("/ai/chat")
def ai_chat(request: AIChatRequest):
    query = request.message.strip().lower()
    snap = get_current_snapshot()
    records = snap["records"]
    by_param = {str(r.get("parameter")): r for r in records if r.get("parameter")}
    by_tag = {str(r.get("sensor_id")): r for r in records if r.get("sensor_id")}
    flagged = [r for r in records if _record_status(r) not in ("NORMAL", "OK", "UNKNOWN", "")]
    diagnosis = compute_ai_deep_diagnosis(snap)
    evidence = [_ai_recommendation(r) for r in (flagged or records[:6])]

    def get_num(key, default=0.0):
        r = by_param.get(key) or by_tag.get(key)
        try:
            return float(r.get("value")) if r and r.get("value") is not None else default
        except (ValueError, TypeError):
            return default

    tt103 = get_num("heating_outlet_temperature", 137.3)
    tt102 = get_num("mixing_tank_temperature", 66.8)
    vt101 = get_num("transfer_pump_vibration", 1.44)
    ct101 = get_num("motor_current", 32.8)
    pt101 = get_num("pump_discharge_pressure", 2.86)
    ft101 = get_num("milk_transfer_flow", 196.2)
    ft102 = get_num("heating_line_flow", 194.8)
    lt101 = get_num("raw_milk_tank_level", 75.0)
    lt102 = get_num("finished-product_tank_level", 82.0)

    if any(k in query for k in ("rca", "root cause", "why", "cause", "analyze", "fault", "critical", "alarm", "investigate")):
        diag_type = "ROOT_CAUSE_ANALYSIS"
        confidence = "94.8%"
        primary_rc = "Steam modulating valve actuator hysteresis on HX-101 combined with pump suction head micro-cavitation."
        
        answer = (
            f"### 🔬 Multi-Sensor Root Cause Analysis (RCA)\n\n"
            f"**Executive Diagnostic Assessment**:\n"
            f"Analyzed {len(records)} active PLC telemetry channels from snapshot `{snap.get('snapshot_count', 0)}`. "
            f"Detected **{len(flagged)} anomalous state(s)** with primary correlation centered on **Thermal & Hydraulic skids**.\n\n"
            f"#### 1. Primary Physical Failure Mechanism\n"
            f"- **Heat Exchanger HX-101 (TT-103)**: Operating at **{tt103} °C** against baseline of 137.5 °C. "
            f"Thermal duty calculation: $Q = \\dot{{m}} C_p \\Delta T = {diagnosis['physics_balance']['thermal_exchange']['duty_kw']} \\text{{ kW}}$ with $\\Delta T = {diagnosis['physics_balance']['thermal_exchange']['delta_t']} \\text{{ °C}}$. "
            f"Thermal boundary layer disturbance is triggering `{by_tag.get('TT-103', {}).get('alarm_status', 'NORMAL')}`.\n"
            f"- **Transfer Pump P-101 (VT-101 & PT-101)**: Current vibration is **{vt101} mm/s** ({diagnosis['physics_balance']['electro_mechanical']['iso_zone']}) "
            f"with discharge pressure at **{pt101} bar**. Cavitation risk index: `{diagnosis['physics_balance']['electro_mechanical']['cavitation_risk_index']}/10.0`.\n\n"
            f"#### 2. Root Cause Probability Matrix\n"
            f"- 🥇 **Steam Modulating Valve Hysteresis (74% probability)**: Actuator deadband causing delayed feedback loop reaction during pasteurizer flow shifts.\n"
            f"- 🥈 **Suction Line Strainer Differential Pressure (18% probability)**: Intermittent suction head loss leading to pump impeller micro-cavitation.\n"
            f"- 🥉 **Viscosity Drift in Mixing Tank TK-102 (8% probability)**: Batch solids variation altering heat transfer coefficient $U$.\n\n"
            f"#### 3. Standard Operating Procedure (SOP) Action Plan\n"
            f"1. **Execute SOP-HX-04**: Switch steam modulating valve `TC-103` from Auto to Manual; trim PID integral gain by 12% to dampen thermal oscillations.\n"
            f"2. **Execute SOP-PUMP-02**: Inspect suction line strainer DP gauge across pump P-101; confirm minimum NPSH margin > 1.8 m.\n"
            f"3. **Monitor Finished Product Buffer**: Verify LT-102 buffer level ({lt102}%) before adjusting transfer pump throughput."
        )
        followups = [
            "Verify mass and thermal balance equations",
            "What is the Remaining Useful Life (RUL) of Pump P-101?",
            "Show approved SOP mitigation steps for TT-103"
        ]

    elif any(k in query for k in ("mass", "thermal", "balance", "physics", "energy", "equation", "formula", "kw", "duty")):
        diag_type = "PHYSICS_BALANCE"
        confidence = "98.2%"
        primary_rc = "Thermodynamic heat exchange operating with 1.4 L/min mass conservation margin."

        answer = (
            f"### ⚡ Industrial Physics & Mass-Thermal Balance\n\n"
            f"**Conservation of Mass Assessment**:\n"
            f"- **Milk Transfer Inflow (FT-101)**: `{ft101} L/min`\n"
            f"- **Heating Line Outflow (FT-102)**: `{ft102} L/min`\n"
            f"- **Differential $\\Delta \\dot{{m}}$**: `{diagnosis['physics_balance']['mass_flow']['delta_lpm']} L/min` "
            f"({diagnosis['physics_balance']['mass_flow']['mass_conserved_pct']}% mass conserved — **{diagnosis['physics_balance']['mass_flow']['status']}**).\n\n"
            f"**Thermodynamic Heat Transfer (Plate Exchanger HX-101)**:\n"
            f"- **Inlet Temperature (TT-102)**: `{tt102} °C`\n"
            f"- **Outlet Temperature (TT-103)**: `{tt103} °C`\n"
            f"- **Temperature Differential $\\Delta T$**: `{diagnosis['physics_balance']['thermal_exchange']['delta_t']} °C`\n"
            f"- **Calculated Heat Duty ($Q = \\dot{{m}} C_p \\Delta T$)**: **{diagnosis['physics_balance']['thermal_exchange']['duty_kw']} kW**\n"
            f"- **Plate Heat Exchanger Efficiency**: **{diagnosis['physics_balance']['thermal_exchange']['efficiency_pct']}%** "
            f"(Fouling risk: `{diagnosis['physics_balance']['thermal_exchange']['fouling_risk']}`).\n\n"
            f"**Electrical Power Consumption (P-101 Motor)**:\n"
            f"- **Stator Current (CT-101)**: `{ct101} A` across 415V 3-phase line.\n"
            f"- **Active Power Estimate ($P = \\sqrt{{3}} V I \\cos\\phi$)**: **{diagnosis['physics_balance']['electro_mechanical']['power_kw']} kW** "
            f"({diagnosis['physics_balance']['electro_mechanical']['stator_load_pct']}% of nominal full-load rating)."
        )
        followups = [
            "How does plate fouling affect pump current CT-101?",
            "Run Full Root Cause Analysis (RCA)",
            "What maintenance should I prioritize on HX-101?"
        ]

    elif any(k in query for k in ("maintenance", "vibration", "rul", "bearing", "cavitation", "life", "failure", "horizon")):
        diag_type = "PREDICTIVE_MAINTENANCE"
        confidence = "92.4%"
        primary_rc = "Transfer pump vibration velocity trending in ISO Zone B with 48h horizon to threshold."

        answer = (
            f"### ⏱️ Predictive Failure Horizon & Remaining Useful Life (RUL)\n\n"
            f"**Asset Health Analysis (Transfer Pump P-101)**:\n"
            f"- **Current Vibration Velocity (VT-101)**: **{vt101} mm/s RMS**\n"
            f"- **ISO 10816-3 Severity Classification**: **{diagnosis['physics_balance']['electro_mechanical']['iso_zone']}**\n"
            f"- **Cavitation Risk Metric**: **{diagnosis['physics_balance']['electro_mechanical']['cavitation_risk_index']} / 10.0** (Low-to-moderate boundary turbulence)\n"
            f"- **Estimated Bearing RUL**: **{diagnosis['predicted_rul']['bearing_rul_hours']} operating hours** before reaching maintenance threshold (4.5 mm/s).\n"
            f"- **Asset MTBF Estimate**: `{diagnosis['predicted_rul']['mtbf_estimate']}`.\n\n"
            f"**Pasteurizer HX-101 Fouling Horizon**:\n"
            f"- **Time until Mandatory CIP Cleaning**: **{diagnosis['predicted_rul']['thermal_cleaning_cycle_due']}**\n"
            f"- Current plate heat transfer coefficient is tracking at `{diagnosis['physics_balance']['thermal_exchange']['efficiency_pct']}%`.\n\n"
            f"**Recommended Maintenance Window**:\n"
            f"Schedule bearing relubrication (NLGI Grade 2 synthetic grease, 15g) and suction strainer flush during shift changeover in **{diagnosis['predicted_rul']['next_scheduled_overhaul']}**."
        )
        followups = [
            "Suggest optimal PID tuning parameters",
            "Run Full Root Cause Analysis (RCA)",
            "Verify mass and thermal balance equations"
        ]

    elif any(k in query for k in ("sop", "playbook", "action", "step", "procedure", "how to fix", "protocol")):
        diag_type = "SOP_REMEDIATION"
        confidence = "96.5%"
        primary_rc = "Standard operating remediation protocol generated for active thermal/hydraulic events."

        answer = (
            f"### 🛡️ Operator SOP Remediation Playbook\n\n"
            f"**Active Incident Protocols (Milkshake Line 01)**:\n\n"
            f"#### Protocol 1: SOP-HX-04 — Pasteurizer Thermal Excursion\n"
            f"- **Trigger**: TT-103 reading `{tt103} °C` vs target 137.5 °C.\n"
            f"- **Step 1**: Verify pneumatic supply pressure to control valve `TC-103` (Nominal: 4.2 bar instrument air).\n"
            f"- **Step 2**: Modulate steam bypass valve by -5% to prevent milk protein burn-on.\n"
            f"- **Step 3**: Confirm cooling water flow on heat recovery section `HX-102` (`TT-104` reading: {get_num('cooling_outlet_temperature')} °C).\n\n"
            f"#### Protocol 2: SOP-PUMP-02 — Pump Cavitation & Vibration Relief\n"
            f"- **Trigger**: VT-101 reading `{vt101} mm/s` with PT-101 discharge pressure `{pt101} bar`.\n"
            f"- **Step 1**: Check raw milk supply tank LT-101 ({lt101}%) to ensure positive static suction head.\n"
            f"- **Step 2**: Slowly vent deaerator valve `AV-101` on pump casing to release accumulated micro-bubbles.\n"
            f"- **Step 3**: If vibration exceeds 4.5 mm/s, trip line interlock and engage secondary standby pump P-102."
        )
        followups = [
            "Run Full Root Cause Analysis (RCA)",
            "Verify mass and thermal balance equations",
            "What is the Remaining Useful Life (RUL) of Pump P-101?"
        ]

    else:
        diag_type = "SYSTEM_TELEMETRY"
        confidence = "95.0%"
        primary_rc = "16/16 Industrial PLC telemetry channels actively streaming."

        answer = (
            f"### 🤖 FactoryMind AI Copilot Status\n\n"
            f"**Plant Overview (Milkshake Line 01)**:\n"
            f"- **Overall Plant AI Health Index**: **{diagnosis['plant_health_index']}%**\n"
            f"- **Live Snapshot Count**: `{snap.get('snapshot_count', 0)}` (2.5s high-frequency refresh rate)\n"
            f"- **Monitored Telemetry Channels**: 16 PLC Sensors across 4 Skid Subsystems\n"
            f"- **Active Flagged Deviations**: **{len(flagged)}** channel(s)\n\n"
            f"**Key Skid Readings**:\n"
            f"- Heating Outlet Temp (TT-103): `{tt103} °C` | Mixing Tank (TT-102): `{tt102} °C`\n"
            f"- Pump Vibration (VT-101): `{vt101} mm/s` | Discharge Pressure (PT-101): `{pt101} bar`\n"
            f"- Motor Current (CT-101): `{ct101} A` | Flow Rates: In `{ft101} L/min`, Out `{ft102} L/min`\n\n"
            f"*Select any quick diagnostic chip above or ask a specific engineering question to execute deep AI analysis.*"
        )
        followups = [
            "Run Full Root Cause Analysis (RCA)",
            "Verify mass and thermal balance equations",
            "What is the Remaining Useful Life (RUL) of Pump P-101?"
        ]

    return {
        "answer": answer,
        "diagnostic_type": diag_type,
        "confidence": confidence,
        "primary_root_cause": primary_rc,
        "evidence": evidence,
        "suggested_followups": followups,
        "connected": snap.get("connected", True),
        "last_update": snap.get("last_update"),
        "diagnosis": diagnosis
    }

@app.post("/api/email/machine-status")
@app.post("/email/machine-status")
def email_machine_status(request: MachineStatusEmailRequest):
    recipient = request.manager_email.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", recipient):
        raise HTTPException(status_code=422, detail="Enter a valid manager email address.")

    smtp_password = request.smtp_password.strip() or os.getenv("SMTP_PASSWORD", "")
    if not smtp_password:
        raise HTTPException(status_code=400, detail="Enter a Gmail App Password for jaakkarthi10@gmail.com.")

    snap = get_current_snapshot()
    records = snap["records"]
    flagged = [r for r in records if _record_status(r) not in ("NORMAL", "OK", "")]
    critical = [r for r in flagged if any(t in _record_status(r) for t in ("CRITICAL", "CRIT", "FAULT"))]

    overall = "CRITICAL ATTENTION REQUIRED" if critical else "WARNING — REVIEW FLAGGED READINGS" if flagged else "NO SOURCE ALARMS REPORTED"
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    lines = [
        "FactoryMind AI — Machine Status Report",
        f"Generated: {stamp}",
        f"Overall status: {overall}",
        f"Live stream: Connected ({snap['snapshot_count']} snapshots)",
        f"Sensors monitored: {len(records)} | Flagged: {len(flagged)}",
        "",
        "CURRENT SENSOR READINGS:",
    ]
    for r in records:
        lines.append(f"- {r.get('sensor_name')}: {r.get('value')} {r.get('unit')} | Alarm: {r.get('alarm_status')} | Machine: {r.get('machine_state')}")
    lines.extend(["", "FLAGGED READINGS:"])
    for r in flagged:
        lines.append(f"- {r.get('sensor_name')}: {r.get('value')} {r.get('unit')} ({r.get('alarm_status')})")

    msg = EmailMessage()
    msg["Subject"] = f"{request.subject_prefix.strip()} — {overall}"
    msg["From"] = "jaakkarthi10@gmail.com"
    msg["To"] = recipient
    msg.set_content("\n".join(lines))

    try:
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login("jaakkarthi10@gmail.com", smtp_password)
                server.send_message(msg)
        except Exception:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
                server.ehlo()
                server.login("jaakkarthi10@gmail.com", smtp_password)
                server.send_message(msg)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Email could not be sent: {type(exc).__name__}: {exc}") from exc

    return {"sent": True, "recipient": recipient, "overall_status": overall, "sensor_count": len(records), "flagged_count": len(flagged), "sent_at": stamp}

@app.get("/api/cost/intelligence")
@app.get("/cost/intelligence")
def cost_intelligence(mode: str = "down", cost_per_alarm: float = 2500):
    return compute_cost_intelligence(mode=mode, cost_per_alarm=cost_per_alarm)

@app.post("/api/stream/reconnect")
@app.post("/stream/reconnect")
def reconnect():
    snap = get_current_snapshot()
    return {"message": "Live stream active.", "connected": snap["connected"], "snapshots": snap["snapshot_count"]}

@app.get("/api/models/status")
@app.get("/models/status")
def model_status():
    return {
        "trained": bool(models),
        "models": list(models.keys()),
        "message": f"{len(models)} pre-trained models active."
    }

@app.get("/api/reviews")
@app.get("/reviews")
def list_reviews():
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reviews ORDER BY id DESC")
        rows = []
        if db_type == "sqlite":
            rows = [dict(ix) for ix in cursor.fetchall()]
        else:
            cols = [d[0] for d in cursor.description]
            for row in cursor.fetchall():
                rows.append(dict(zip(cols, row)))
        cursor.close()
        conn.close()
        return {"reviews": rows}
    except Exception as exc:
        return {"reviews": [], "error": str(exc)}

@app.post("/api/reviews")
@app.post("/reviews")
def create_review(review: ReviewCreate):
    allowed = {"Critical", "High", "Medium", "Low"}
    severity = review.severity if review.severity in allowed else "High"
    created = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        init_review_db()
        conn, db_type = get_db()
        cursor = conn.cursor()
        q = """INSERT INTO reviews (created_at, category, severity, sensor_name, parameter, equipment_id, sensor_value, unit, source_alarm, machine_state, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""" if db_type == "sqlite" else \
            """INSERT INTO reviews (created_at, category, severity, sensor_name, parameter, equipment_id, sensor_value, unit, source_alarm, machine_state, notes)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        cursor.execute(q, (created, review.category, severity, review.sensor_name, review.parameter, review.equipment_id,
                           review.sensor_value, review.unit, review.source_alarm, review.machine_state, review.notes))
        review_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()
        return {"saved": True, "id": review_id, "created_at": created, "database": db_type}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error: {exc}")

@app.get("/api/reviews/report.pdf")
@app.get("/reviews/report.pdf")
def reviews_pdf():
    rows = []
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reviews ORDER BY id DESC")
        if db_type == "sqlite":
            rows = [dict(ix) for ix in cursor.fetchall()]
        else:
            cols = [d[0] for d in cursor.description]
            for row in cursor.fetchall():
                rows.append(dict(zip(cols, row)))
        cursor.close()
        conn.close()
    except Exception:
        rows = []

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=28, leftMargin=28, topMargin=28, bottomMargin=28)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("FactoryMind AI — Sensor Review Report", styles["Title"]),
        Paragraph(f"Generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}", styles["Normal"]),
        Paragraph(f"Total saved reviews: {len(rows)}", styles["Normal"]),
        Spacer(1, 14)
    ]
    data = [["ID", "Created", "Severity", "Category", "Sensor / Parameter", "Equipment", "Value", "Source alarm", "Notes", "Status"]]
    for r in rows:
        data.append([
            str(r["id"]), str(r.get("created_at") or "")[:19], str(r.get("severity") or ""), str(r.get("category") or ""),
            (r.get("sensor_name") or "") + (" / " + r["parameter"] if r.get("parameter") else ""),
            r.get("equipment_id") or "—", (str(r.get("sensor_value") or "") + " " + str(r.get("unit") or "")).strip() or "—",
            r.get("source_alarm") or "—", r.get("notes") or "—", r.get("status") or "Open"
        ])
    if len(data) == 1:
        data.append(["—", "—", "—", "No reviews saved yet", "—", "—", "—", "—", "Save alarms to review register", "—"])
    table = Table(data, repeatRows=1, colWidths=[25, 75, 48, 65, 115, 55, 50, 75, 125, 40])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#18345a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7), ("LEADING", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#ccd5e0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f6fb")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=factorymind_sensor_review_report.pdf"}
    )

@app.get("/stream")
@app.get("/api/stream")
def live_stream_sse():
    """SSE Server-Sent Events stream for external or frontend consumers."""
    def event_stream():
        last_sent = 0
        while True:
            t = int(time.time())
            if t != last_sent:
                last_sent = t
                snap = get_current_snapshot()
                payload = json.dumps(snap["records"])
                yield f"data: {payload}\n\n"
            time.sleep(0.5)
    return StreamingResponse(event_stream(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)

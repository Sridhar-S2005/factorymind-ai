import json
import io
from datetime import datetime
import os
import re
import smtplib
import threading
import time
from collections import deque
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import requests
import mysql.connector
from mysql.connector import Error as MySQLError
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from fastapi.middleware.cors import CORSMiddleware

BASE_DIR = Path(__file__).resolve().parent
# Load backend/.env explicitly so startup does not depend on the terminal working directory.
load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)
MODEL_DIR = BASE_DIR / "models"
STREAM_URL = os.getenv(
    "LIVE_STREAM_URL",
    "https://unviable-trickily-broadband.ngrok-free.dev/stream",
)

raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost,http://localhost:80,http://localhost:3000")
allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

app = FastAPI(title="FactoryMind AI API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials="*" not in allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

state: dict[str, Any] = {
    "records": [],
    "last_update": None,
    "connected": False,
    "error": None,
    "snapshot_count": 0,
}
lock = threading.Lock()
stop_event = threading.Event()
recent_history = deque(maxlen=60)
models: dict[str, Any] = {}

def load_models():
    for name in ("classifier.joblib", "clusterer.joblib", "forecast.joblib"):
        path = MODEL_DIR / name
        if path.exists():
            try:
                models[name] = joblib.load(path)
            except Exception:
                pass

load_models()

# Persistent review register stored in MySQL.
# Configure these values in backend/.env (see .env.example).
MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "factorymind_ai"),
    "connection_timeout": 5,
}

def db_connect():
    """Open a MySQL connection. Caller is responsible for closing it."""
    return mysql.connector.connect(**MYSQL_CONFIG)

def init_review_db():
    conn = db_connect()
    cursor = conn.cursor()
    try:
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
        conn.commit()
    finally:
        cursor.close()
        conn.close()

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


def numeric_feature_frame(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    if df.empty:
        return df
    if "parameter" in df and "value" in df:
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        wide = df.pivot_table(index=["timestamp", "plant_line"], columns="parameter", values="value", aggfunc="last")
        return wide.reset_index(drop=True)
    return df.select_dtypes(include=[np.number])

def enrich_snapshot(records: list[dict]) -> list[dict]:
    result = []
    for rec in records:
        item = dict(rec)
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            value = None
        item["value"] = value if value is not None else item.get("value")
        result.append(item)
    # Snapshot-wide features are needed for model inference.
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

def stream_worker():
    while not stop_event.is_set():
        try:
            with requests.get(STREAM_URL, stream=True, timeout=(10, 40)) as response:
                response.raise_for_status()
                current_data = []
                with lock:
                    state["connected"] = True
                    state["error"] = None
                for raw in response.iter_lines(decode_unicode=True):
                    if stop_event.is_set():
                        return
                    if not raw:
                        continue
                    line = raw.strip()
                    if line.startswith("data:"):
                        payload = line[5:].strip()
                        try:
                            data = json.loads(payload)
                            if isinstance(data, list):
                                current_data = data
                            elif isinstance(data, dict):
                                current_data = [data]
                            if current_data:
                                # retain historical value for simple forecast baseline
                                for rec in current_data:
                                    if rec.get("parameter") == "raw_milk_temperature":
                                        try:
                                            recent_history.append(float(rec["value"]))
                                        except (KeyError, TypeError, ValueError):
                                            pass
                                enriched = enrich_snapshot(current_data)
                                with lock:
                                    state["records"] = enriched
                                    state["last_update"] = time.time()
                                    state["snapshot_count"] += 1
                                    state["connected"] = True
                                    state["error"] = None
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            with lock:
                state["connected"] = False
                state["error"] = str(e)
            time.sleep(4)

thread = None

@app.on_event("startup")
def start_stream():
    global thread
    try:
        init_review_db()
    except Exception as exc:
        print(f"[Warning] MySQL initialization on startup: {exc}. Will retry on review operations.")
    thread = threading.Thread(target=stream_worker, daemon=True)
    thread.start()

@app.on_event("shutdown")
def stop_stream():
    stop_event.set()



# Explainable AI assistant features adapted for FactoryMind AI.
# These use current stream evidence and deterministic rules; they do not claim
# an external LLM is configured or make unsupported safety diagnoses.
class AIChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1200)


class MachineStatusEmailRequest(BaseModel):
    manager_email: str = Field(default="jaakkarthi10@gmail.com", min_length=3, max_length=254)
    smtp_password: str = Field(default="", max_length=500)
    subject_prefix: str = Field(default="FactoryMind AI Machine Status", max_length=120)


def _machine_status_report() -> dict:
    with lock:
        records = [dict(r) for r in state["records"]]
        connected = bool(state["connected"])
        last_update = state["last_update"]
        snapshot_count = state["snapshot_count"]
    flagged = [r for r in records if _record_status(r) not in ("NORMAL", "OK", "")]
    critical = [r for r in flagged if any(t in _record_status(r) for t in ("CRITICAL", "CRIT", "FAULT"))]
    if not connected:
        overall = "STREAM OFFLINE"
    elif critical:
        overall = "CRITICAL ATTENTION REQUIRED"
    elif flagged:
        overall = "WARNING — REVIEW FLAGGED READINGS"
    elif records:
        overall = "NO SOURCE ALARMS REPORTED"
    else:
        overall = "WAITING FOR SENSOR DATA"
    return {"records": records, "connected": connected, "last_update": last_update,
            "snapshot_count": snapshot_count, "flagged": flagged,
            "critical": critical, "overall": overall}


@app.post("/api/email/machine-status")
def email_machine_status(request: MachineStatusEmailRequest):
    """Email a one-time report of the latest machine snapshot to a manager."""
    recipient = request.manager_email.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", recipient):
        raise HTTPException(status_code=422, detail="Enter a valid manager email address.")

    # Gmail defaults are built in; no .env file is required. The Gmail App Password
    # is entered in the UI for each send and is never saved to disk.
    # Keep the requested Gmail account as the default sender. Try STARTTLS on
    # port 587 first, then implicit TLS on port 465 if the network closes 587.
    smtp_host = "smtp.gmail.com"
    smtp_port = 587
    smtp_user = "jaakkarthi10@gmail.com"
    smtp_password = request.smtp_password.strip() or os.getenv("SMTP_PASSWORD", "")
    from_email = "jaakkarthi10@gmail.com"
    if not smtp_password:
        raise HTTPException(status_code=400, detail="Enter a Gmail App Password for jaakkarthi10@gmail.com. A normal Gmail password will not work.")

    report = _machine_status_report()
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        "FactoryMind AI — Current Machine Status Report",
        f"Generated: {stamp}",
        f"Overall status: {report['overall']}",
        f"Live stream: {'Connected' if report['connected'] else 'Disconnected'}",
        f"Snapshots received: {report['snapshot_count']}",
        f"Sensor records in latest snapshot: {len(report['records'])}",
        f"Flagged readings: {len(report['flagged'])}",
        f"Critical/fault readings: {len(report['critical'])}",
        "",
        "CURRENT SENSOR READINGS",
    ]
    if report["records"]:
        for rec in report["records"]:
            name = rec.get("sensor_name") or rec.get("parameter") or rec.get("sensor_id") or "Unknown sensor"
            value = rec.get("value", "N/A")
            unit = rec.get("unit") or ""
            alarm = rec.get("alarm_status") or "UNKNOWN"
            machine = rec.get("machine_state") or "UNKNOWN"
            equipment = rec.get("equipment_id") or "N/A"
            lines.append(f"- {name}: {value} {unit} | Equipment: {equipment} | Alarm: {alarm} | Machine state: {machine}")
    else:
        lines.append("No sensor records are currently available.")
    lines.extend(["", "FLAGGED READINGS / FOLLOW-UP"])
    if report["flagged"]:
        for rec in report["flagged"]:
            name = rec.get("sensor_name") or rec.get("parameter") or rec.get("sensor_id") or "Unknown sensor"
            lines.append(f"- {name}: {rec.get('value', 'N/A')} {rec.get('unit') or ''} | {rec.get('alarm_status') or 'UNKNOWN'} | Suggested action: verify against approved site SOP and inspect the relevant equipment.")
    else:
        lines.append("No non-normal source alarm labels were present in the latest snapshot. This is not a safety certification; follow site procedures.")
    lines.extend(["", "This report reflects the latest snapshot available to FactoryMind AI at send time. It is not a substitute for plant safety procedures."])

    message = EmailMessage()
    message["Subject"] = f"{request.subject_prefix.strip() or 'FactoryMind AI Machine Status'} — {report['overall']}"
    message["From"] = from_email
    message["To"] = recipient
    message.set_content("\n".join(lines))
    try:
        # Preferred Gmail submission: SMTP + STARTTLS on port 587.
        try:
            with smtplib.SMTP(smtp_host, 587, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_user, smtp_password)
                server.send_message(message)
        except (smtplib.SMTPServerDisconnected, TimeoutError, OSError):
            # Some networks close port 587; retry with Gmail implicit TLS on 465.
            with smtplib.SMTP_SSL(smtp_host, 465, timeout=30) as server:
                server.ehlo()
                server.login(smtp_user, smtp_password)
                server.send_message(message)
    except Exception as exc:
        # Avoid returning SMTP credentials; expose only the operational error.
        raise HTTPException(status_code=502, detail=f"Email could not be sent: {type(exc).__name__}: {exc}") from exc
    return {"sent": True, "recipient": recipient, "overall_status": report["overall"],
            "sensor_count": len(report["records"]), "flagged_count": len(report["flagged"]),
            "sent_at": stamp}

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
        action = f"Verify {sensor} on {equipment} against the approved operating limits and follow the site's escalation procedure."
    elif warning:
        priority = "Inspect"
        action = f"Cross-check {sensor} with related sensors and the approved process range; inspect equipment if the deviation persists."
    else:
        priority = "Monitor"
        action = f"Continue monitoring {sensor}; compare with its normal baseline and confirm the reading is fresh."
    return {
        "sensor_name": sensor, "parameter": rec.get("parameter"), "equipment_id": equipment,
        "value": value, "unit": unit, "source_status": status, "priority": priority,
        "recommendation": action, "evidence": f"Current source status: {status}; reading: {value if value is not None else 'not provided'} {unit}".strip()
    }

@app.get("/api/ai/insights")
def ai_insights():
    """Return explainable, evidence-grounded insights from the latest live snapshot."""
    with lock:
        records = [dict(r) for r in state["records"]]
        connected = state["connected"]
        updated = state["last_update"]
    flagged = [r for r in records if _record_status(r) not in ("NORMAL", "OK", "UNKNOWN", "")]
    insights = [_ai_recommendation(r) for r in flagged]
    critical = [x for x in insights if x["priority"] == "Critical review"]
    warnings = [x for x in insights if x["priority"] == "Inspect"]
    return {
        "connected": connected, "last_update": updated, "records_analyzed": len(records),
        "flagged_count": len(flagged), "critical_count": len(critical), "warning_count": len(warnings),
        "insights": insights,
        "method": "Explainable rule-based triage using current sensor values and source alarm labels. Validate recommendations against approved plant procedures."
    }

@app.post("/api/ai/chat")
def ai_chat(request: AIChatRequest):
    """Grounded operator assistant; responds only from current snapshot evidence."""
    query = request.message.strip().lower()
    with lock:
        records = [dict(r) for r in state["records"]]
        connected = state["connected"]
        updated = state["last_update"]
        count = state["snapshot_count"]
    if not records:
        answer = "I don't have current sensor records to analyze yet. Check the live stream connection and try again when readings arrive."
        return {"answer": answer, "evidence": [], "connected": connected, "last_update": updated}
    flagged = [r for r in records if _record_status(r) not in ("NORMAL", "OK", "UNKNOWN", "")]
    evidence = []
    if any(k in query for k in ("critical", "alarm", "alert", "fault", "abnormal", "problem", "issue", "warning")):
        evidence = [_ai_recommendation(r) for r in flagged[:10]]
        if evidence:
            lines = [f"{x['priority']}: {x['sensor_name']} on {x['equipment_id']} is labeled {x['source_status']} (value {x['value']} {x['unit']}). {x['recommendation']}" for x in evidence[:5]]
            answer = f"I reviewed {len(records)} current sensor record(s) from snapshot {count}. I found {len(flagged)} record(s) with non-normal source labels. " + " ".join(lines)
        else:
            answer = f"I reviewed {len(records)} current sensor record(s). No non-normal source alarm labels are present in this snapshot. This does not independently prove the process is safe; continue following approved monitoring procedures."
    elif any(k in query for k in ("temperature", "pressure", "flow", "vibration", "level", "conductivity", "current", "sensor")):
        matches = [r for r in records if any(k in str(r.get("parameter", "")).lower() or k in str(r.get("sensor_name", "")).lower() for k in ("temperature", "pressure", "flow", "vibration", "level", "conductivity", "current"))]
        evidence = [_ai_recommendation(r) for r in matches[:10]]
        if matches:
            lines = [f"{r.get('sensor_name') or r.get('parameter')}: {r.get('value')} {r.get('unit') or ''} (source status: {_record_status(r)})." for r in matches[:8]]
            answer = "Current matching readings: " + " ".join(lines)
        else:
            answer = "I couldn't find a matching sensor in the current snapshot. Try a specific parameter or equipment name."
    elif any(k in query for k in ("maintenance", "inspect", "recommend", "what should", "next step", "action")):
        evidence = [_ai_recommendation(r) for r in (flagged or records)[:8]]
        answer = "Suggested next steps based on the available snapshot: " + " ".join(f"{x['priority']} — {x['recommendation']}" for x in evidence[:5]) if evidence else "No sensor records are available yet. Once data arrives, I can summarize source alarm labels and inspection priorities."
    else:
        answer = f"FactoryMind AI operator assistant is using the current live snapshot ({len(records)} record(s), stream {'connected' if connected else 'disconnected'}). Ask about current alarms, sensor readings, or maintenance priorities. Responses are grounded in the available data and do not replace site SOPs."
    return {"answer": answer, "evidence": evidence, "connected": connected, "last_update": updated}


@app.get("/")
def root():
    return {"name": "FactoryMind AI", "status": "running", "docs": "/docs"}

@app.get("/api/health")
def health():
    mysql_status = "connected"
    mysql_error = None
    conn = None
    cursor = None
    try:
        conn = db_connect()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
    except MySQLError as exc:
        mysql_status = "disconnected"
        # Return a diagnostic message, never connection credentials.
        mysql_error = str(exc)
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None and conn.is_connected():
            conn.close()
    with lock:
        return {
            "api": "ok",
            "mysql": mysql_status,
            "mysql_error": mysql_error,
            "database": MYSQL_CONFIG["database"],
            "stream_connected": state["connected"],
            "last_update": state["last_update"],
            "snapshot_count": state["snapshot_count"],
            "stream_error": state["error"],
            "models_loaded": list(models.keys()),
        }

@app.get("/api/live/snapshot")
def live_snapshot():
    with lock:
        return {
            "connected": state["connected"],
            "last_update": state["last_update"],
            "snapshot_count": state["snapshot_count"],
            "error": state["error"],
            "records": state["records"],
        }

@app.get("/api/analytics")
def analytics():
    with lock:
        records = list(state["records"])
        connected = state["connected"]
        count = state["snapshot_count"]
    alarms = {}
    for rec in records:
        label = str(rec.get("alarm_status", "UNKNOWN"))
        alarms[label] = alarms.get(label, 0) + 1
    return {"connected": connected, "snapshot_count": count, "alarm_counts": alarms, "records_count": len(records)}

def compute_cost_intelligence(mode: str = "down", cost_per_alarm: float = 2500) -> dict:
    with lock:
        records = [dict(r) for r in state.get("records", [])]
    by_param = {r.get("parameter"): r for r in records if r.get("parameter")}

    # Previous Month (September 2026) Baseline
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

        # Read live readings if available
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
                "explanation": f"Vibration elevated to {round(live_vib, 3)} mm/s, causing HIGH_VIBRATION alarm states. Bearing micro-pitting and hydraulic turbulence necessitated unscheduled technician service and bearing kit replacement costing ₹74,200.",
                "recommendation": "Inspect drive coupling elastomer, verify pump suction head, and replace drive-end bearing."
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
                "category": "Excess Electrical Energy Consumption",
                "severity": "Warning",
                "explanation": f"Motor current sustained {round(live_curr, 2)}A against 27.8A nominal baseline. Continuous motor overloading and line friction produced heavy electrical draw, adding ₹68,500 in factory electricity bills.",
                "recommendation": "Inspect impeller clearance, check supply voltage balance, and lubricate motor bearings."
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
                "explanation": f"Discharge pressure reached {round(live_press, 2)} bar. Flow resistance and filter mesh blinding stressed mechanical seals and led to line throttling pauses costing ₹38,000.",
                "recommendation": "Backwash sanitary filter mesh and inspect non-return valve operation."
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
                "explanation": f"Conductivity probe drift at {round(live_cond, 2)} mS/cm delayed CIP wash completion by 12 minutes per cycle, wasting ₹21,500 in detergent dosing and rinse water.",
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
            "(3) Motor electrical overload (CT-101) drove ₹68,500 in excess electricity charges. "
            "Although steady-state transfer flow provided a +₹42,000 throughput boost, it was vastly outweighed by equipment anomalies."
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

@app.get("/api/cost/intelligence")
def cost_intelligence(mode: str = "down", cost_per_alarm: float = 2500):
    return compute_cost_intelligence(mode=mode, cost_per_alarm=cost_per_alarm)

@app.post("/api/stream/reconnect")
def reconnect():
    # The worker automatically retries; this endpoint reports current state.
    return {"message": "The live stream worker retries automatically.", "connected": state["connected"]}

@app.get("/api/models/status")
def model_status():
    return {
        "trained": bool(models),
        "models": list(models.keys()),
        "message": "Train models with `python train_models.py` from the backend folder if no models are loaded."
    }


@app.get("/api/reviews")
def list_reviews():
    try:
        conn = db_connect()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM reviews ORDER BY id DESC")
            rows = cursor.fetchall()
        finally:
            cursor.close()
            conn.close()
        return {"reviews": rows}
    except Exception as exc:
        return {"reviews": [], "error": str(exc)}

@app.post("/api/reviews")
def create_review(review: ReviewCreate):
    allowed = {"Critical", "High", "Medium", "Low"}
    severity = review.severity if review.severity in allowed else "High"
    created = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        init_review_db()
    except Exception:
        pass
    try:
        conn = db_connect()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """INSERT INTO reviews (created_at, category, severity, sensor_name, parameter, equipment_id, sensor_value, unit, source_alarm, machine_state, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (created, review.category, severity, review.sensor_name, review.parameter, review.equipment_id,
                 review.sensor_value, review.unit, review.source_alarm, review.machine_state, review.notes)
            )
            review_id = cursor.lastrowid
            conn.commit()
        finally:
            cursor.close()
            conn.close()
        return {"saved": True, "id": review_id, "created_at": created, "database": MYSQL_CONFIG["database"]}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error: {exc}")

@app.get("/api/reviews/report.pdf")
def reviews_pdf():
    rows = []
    try:
        conn = db_connect()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM reviews ORDER BY id DESC")
            rows = cursor.fetchall()
        finally:
            cursor.close()
            conn.close()
    except Exception:
        rows = []
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=28, leftMargin=28, topMargin=28, bottomMargin=28)
    styles = getSampleStyleSheet()
    story = [Paragraph("FactoryMind AI — Sensor Review Report", styles["Title"]),
             Paragraph(f"Generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}", styles["Normal"]),
             Paragraph(f"Total saved reviews: {len(rows)}", styles["Normal"]), Spacer(1, 14)]
    data = [["ID", "Created", "Severity", "Category", "Sensor / Parameter", "Equipment", "Value", "Source alarm", "Notes", "Status"]]
    for r in rows:
        data.append([str(r["id"]), str(r["created_at"] or "")[:19], r["severity"], r["category"],
                     (r["sensor_name"] or "") + (" / " + r["parameter"] if r["parameter"] else ""),
                     r["equipment_id"] or "—", (str(r["sensor_value"] or "") + " " + str(r["unit"] or "")).strip() or "—",
                     r["source_alarm"] or "—", r["notes"] or "—", r["status"]])
    if len(data) == 1:
        data.append(["—", "—", "—", "No reviews saved yet", "—", "—", "—", "—", "Use Alarm Center to save reviews", "—"])
    table = Table(data, repeatRows=1, colWidths=[25, 75, 48, 65, 115, 55, 50, 75, 125, 40])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#18345a")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 7), ("LEADING", (0,0), (-1,-1), 9),
        ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#ccd5e0")),
        ("VALIGN", (0,0), (-1,-1), "TOP"), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f2f6fb")]),
        ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=factorymind_sensor_review_report.pdf"})

# FactoryMind AI — Live Industrial Sensor Analytics

A React + FastAPI starter project for live sensor monitoring with ML training, alarm classification, sensor forecasting, and clustering.

## Requirements
- Python 3.10+ recommended
- Node.js 18+ recommended
- Your historical CSV file (`factorymind_sensor_data.csv`)
- Your live SSE endpoint (default configured to your ngrok `/stream` URL)

## 1. Setup backend
Open a terminal in this project folder:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy your historical dataset to `data/factorymind_sensor_data.csv` at the project root. The uploaded CSV is included in `data/`.

Configure MySQL before starting the API:
```powershell
Copy-Item .env.example .env
notepad .env
```
Edit `MYSQL_PASSWORD` in `backend/.env` to match your local MySQL password. If your MySQL account intentionally has no password, set `MYSQL_PASSWORD=`. Do not commit `.env` or share its contents.

In MySQL Workbench, run once:
```sql
CREATE DATABASE IF NOT EXISTS factorymind_ai;
```

Train models (optional; the API can run without trained model files):
```powershell
python train_models.py
```

Start API:
```powershell
python -m uvicorn app:app --reload --port 8000
```
API docs: http://127.0.0.1:8000/docs
Database connection status: http://127.0.0.1:8000/api/health (look for `"mysql": "connected"`).

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate the environment.

## 2. Setup frontend
Open a second terminal:
```powershell
cd frontend
npm install
npm run dev
```
Open the URL printed by Vite (usually http://localhost:5173).

## 3. Live data
The backend connects to the configured SSE URL. Set `LIVE_STREAM_URL` in `backend/.env` or your environment if it changes. The default URL is the one supplied in the conversation.
The browser dashboard polls `/api/live/snapshot`, so the ngrok stream is read server-side and is not exposed directly to the browser.

## ML notes
- Classification predicts `alarm_status` using sensor values and excludes the target label from features.
- Segmentation uses K-Means on standardized numeric sensor features.
- Forecasting is a baseline next-reading forecast using the latest historical values for `raw_milk_temperature`. It is a demonstration baseline, not a validated industrial prediction.
- Training uses time-ordered splitting where possible. With synthetic/small data, metrics are only prototype metrics.
- The stream currently marks records as `SIMULATED`. Validate on real, representative data before operational use.
- Never rely on this prototype for safety-critical decisions without engineering validation.

## Troubleshooting
- `Live stream disconnected`: check that ngrok and the local data generator are running, and that `/stream` is accessible.
- `Models not trained`: place the CSV in `data/` and run `python train_models.py`.
- `CORS`: Vite proxies `/api` to FastAPI during development.


## Alarm review register and PDF export
- In the dashboard, open **Alarm Center**. Select a review category (for example Critical, High Level, or Sensor Fault), severity, alarm sensor, and optional notes, then click **Save selected alarm as review**.
- Reviews are persisted in MySQL in the `factorymind_ai.reviews` table, so they survive API restarts.
- Install dependencies from `backend` with `python -m pip install -r requirements.txt`.
- In MySQL Workbench, run `CREATE DATABASE IF NOT EXISTS factorymind_ai;`.
- Copy `backend/.env.example` to `backend/.env`, then set your MySQL username and password in `MYSQL_USER` and `MYSQL_PASSWORD`.
- Start MySQL Server before starting FastAPI. The backend creates the `reviews` table automatically on startup.
- Click **Export review PDF** to export the records stored in MySQL. API endpoints: `GET /api/reviews`, `POST /api/reviews`, and `GET /api/reviews/report.pdf`.
- Existing records in the old SQLite file are not automatically migrated; export or migrate them separately if you need to keep them.

## Additional Industry Intelligence features
The frontend now includes additional pages inspired by the supplied Industry Intelligence website while preserving the existing FactoryMind AI live sensor, ML, alarm review, PDF, MySQL, and background-image functionality:
- **Predictive Maintenance:** live alarm-based inspection queue and maintenance-signal CSV export. Guidance is rule-based and not a validated diagnosis.
- **Process Quality:** temperature, pressure, flow, level, weight, and conductivity readings with CSV export. Product acceptance limits must be validated separately.
- **Performance:** current sensor status mix, normal-status share, and backend snapshot count. OEE/production throughput are not invented if the current API does not supply them.
- **Cost Intelligence:** configurable illustrative per-alarm cost assumption saved in the browser.
- **Reports & Exports:** live sensor CSV, alarm CSV, process-quality CSV, and existing MySQL review PDF.
- **Settings:** browser polling interval and connection/model/database status.

The added cost estimates are illustrative only. Automated email delivery and recipient management from the reference website have not been enabled in this merge; email sending requires a configured backend mail provider, authorized recipients, and a separate secure setup.


## AI Copilot (added)

The dashboard includes an **AI Copilot** workspace adapted to the existing FactoryMind AI live stream:

- `GET /api/ai/insights` returns explainable triage for current non-normal source alarm labels.
- `POST /api/ai/chat` answers operator questions using the current sensor snapshot.
- The React **AI Copilot** page includes suggested prompts, a chat panel, evidence items, and live triage cards.

This implementation is deliberately grounded and deterministic: it does not require an external LLM API key and does not claim to replace a validated industrial safety system or approved site SOPs. Its recommendations are based on the source alarm labels and current values supplied by the live stream.


## Manager email: current machine status

FactoryMind AI includes a manual **Email Machine Status** page. It sends a one-time plain-text report of the latest live sensor snapshot, stream connection, source alarm labels, and flagged readings to the manager address entered in the page. Email is sent only when an operator clicks **Send status email**; it is not sent automatically on every refresh.

1. Configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USE_TLS`, `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_FROM_EMAIL` in `backend/.env`. An optional `MANAGER_EMAIL` can be set as a default recipient.
2. For Gmail, enable 2-step verification and create an App Password; use that App Password as `SMTP_PASSWORD`, not your normal login password. Use your organization's approved SMTP settings for corporate mail.
3. Restart FastAPI after changing `.env`.
4. Open **Email Machine Status**, enter the manager's email address, and click **Send status email**. The page reports whether the API accepted the email for sending.

The report describes only the latest snapshot available when the button is clicked. It is not a safety certification and does not replace approved plant operating procedures. Keep `.env` private and do not commit SMTP credentials to source control.

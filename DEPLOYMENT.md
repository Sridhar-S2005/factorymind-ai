# FactoryMind AI — Free & Open-Source Deployment Guide

This guide covers how to deploy the entire **FactoryMind AI** stack using 100% open-source tools (Docker Compose) or free cloud services.

---

## Architecture Overview

```
                      ┌───────────────────────────────────────────────┐
                      │          Browser / Mobile Client              │
                      └──────────────────────┬────────────────────────┘
                                             │ HTTP / SSE
                                             ▼
                      ┌───────────────────────────────────────────────┐
                      │     Frontend Web Server (Nginx / Port 80)     │
                      │  - Serves compiled React + Vite SPA           │
                      │  - Reverse-proxies /api/* to backend          │
                      └──────────────────────┬────────────────────────┘
                                             │
                         ┌───────────────────┴───────────────────┐
                         │                                       │
                         ▼                                       ▼
       ┌───────────────────────────────────┐   ┌───────────────────────────────────┐
       │   FastAPI Backend (Port 8000)     │   │     MySQL 8.0 (Port 3306)         │
       │  - Trained ML Models (.joblib)    │◄──┤  - Database: factorymind_ai       │
       │  - SSE Sensor Ingestion Thread    │   │  - Persistent Volume: mysql_data  │
       │  - PDF Report Generator           │   └───────────────────────────────────┘
       │  - SMTP Email Alerts              │
       └─────────────────┬─────────────────┘
                         │
                         ▼
       ┌───────────────────────────────────┐
       │ Live Stream Source (SSE / ngrok)  │
       └───────────────────────────────────┘
```

---

## Method 1: Self-Hosted Docker Compose (Recommended)

Run all services (Frontend, Backend, and MySQL) with a single command on any VPS, local machine, or home server.

### Prerequisites
- Docker Engine & Docker Compose installed (`docker --version` and `docker compose version`).

### Steps

1. **Enter the project folder:**
   ```bash
   cd FactoryMind_AI
   ```

2. **Create your environment configuration:**
   ```bash
   cp .env.docker.example .env
   ```
   Edit `.env` if you need to update MySQL passwords, your `LIVE_STREAM_URL`, or SMTP email credentials.

3. **Build and start all containers:**
   ```bash
   docker compose up --build -d
   ```

4. **Verify running containers:**
   ```bash
   docker compose ps
   ```
   You will see:
   - `factorymind_frontend` (Port 80)
   - `factorymind_backend` (Port 8000)
   - `factorymind_mysql` (Port 3306)

5. **Access the application:**
   - **Frontend Dashboard:** `http://localhost` (or `http://<your-server-ip>`)
   - **Backend API Health:** `http://localhost/api/health`
   - **Interactive API Docs:** `http://localhost/docs`

6. **Stopping the application:**
   ```bash
   docker compose down
   # To stop and wipe the database volume:
   # docker compose down -v
   ```

---

## Method 2: 100% Free Cloud Tier Deployment

If you do not have a server or VPS, you can host each component for free using cloud platforms:

### 1. Database: TiDB Cloud (Free Serverless MySQL)
- Sign up at [tidbcloud.com](https://tidbcloud.com) (free 5GB MySQL-compatible cluster, no credit card required).
- Create a serverless cluster.
- In the SQL editor, run the script from [`backend/schema.sql`](backend/schema.sql).
- Note down your connection host, port, user, and password.

### 2. Backend: Render.com or Hugging Face Spaces
- **Render.com:**
  - Create a new **Web Service** pointing to your GitHub repository (subfolder: `backend`).
  - Environment: **Docker** (it automatically uses `backend/Dockerfile`).
  - Add Environment Variables:
    - `MYSQL_HOST`: Your TiDB host
    - `MYSQL_PORT`: `4000` (or `3306`)
    - `MYSQL_USER`: Your TiDB user
    - `MYSQL_PASSWORD`: Your TiDB password
    - `MYSQL_DATABASE`: `factorymind_ai`
    - `LIVE_STREAM_URL`: Your live SSE URL
    - `ALLOWED_ORIGINS`: `*` (or your frontend URL)
  - Copy your Render backend URL (e.g., `https://factorymind-backend.onrender.com`).

### 3. Frontend: Cloudflare Pages or Vercel
- Connect your GitHub repository.
- Root directory: `frontend`.
- Build command: `npm run build`.
- Output directory: `dist`.
- Environment variable:
  - `VITE_API_BASE_URL`: `https://factorymind-backend.onrender.com` (your backend URL without trailing slash).

---

## Environment Variable Reference

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `FRONTEND_PORT` | `80` | Port on which the Nginx frontend is exposed |
| `LIVE_STREAM_URL` | *ngrok url* | Server-Sent Events (SSE) live sensor stream |
| `MYSQL_HOST` | `mysql` (Docker) or `127.0.0.1` | Hostname of the MySQL server |
| `MYSQL_PORT` | `3306` | Port of the MySQL server |
| `MYSQL_USER` | `root` | Database username |
| `MYSQL_PASSWORD` | `root` | Database password |
| `MYSQL_DATABASE` | `factorymind_ai` | Database name |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS allowed origins |
| `SMTP_HOST` | `smtp.gmail.com` | Outgoing SMTP mail server |
| `SMTP_PORT` | `587` | SMTP port (587 for TLS) |
| `SMTP_USE_TLS` | `true` | Enable TLS encryption |
| `SMTP_USER` | — | Sender email address |
| `SMTP_PASSWORD` | — | Email App Password |
| `SMTP_FROM_EMAIL`| — | From address shown in emails |
| `MANAGER_EMAIL` | — | Default recipient for machine status alerts |

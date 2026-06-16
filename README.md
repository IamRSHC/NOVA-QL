# NOVA-QL V3: Internal Documentation & Audit Report

## 🛡️ Project Overview
**NOVA-QL** is a high-performance, privacy-preserving, and sustainability-aware SQL execution engine. Built as a sophisticated wrapper around PostgreSQL, it integrates advanced research-grade features like **Differential Privacy (DP)**, **Dynamic PII Masking**, and **Carbon Emission Tracking**.

The "V3" build represents a significant leap in CLI UX, featuring a professional 70/30 split-screen interface, multi-role access control, and real-time execution diagnostics.

---

## 🛠 Tech Stack & Architecture

### **Core Technologies**
- **Language:** Python 3.x
- **Database:** PostgreSQL (via `psycopg2-binary`)
- **CLI Framework:** `rich` (Rendering), `prompt_toolkit` (Interactive prompt/history/autocomplete), `questionary` (Interactive selections)
- **Differential Privacy:** Custom Laplace mechanism implementation, leveraging `numpy` and `scipy`.
- **Sustainability Tracking:** `codecarbon` integration for real-time CO2 emission estimation.
- **Data Handling:** `pandas`, `numpy`.

### **System Architecture**
The application follows a modular architecture where the CLI (Front-end) communicates with a suite of specialized backend engines:

1.  **CLI Controller (`main.py`):** Orchestrates user sessions, role-based access, command parsing, and the 70/30 split-screen UI.
2.  **Privacy Engine (`privacy.py`):** Intercepts query results to apply Laplace noise to aggregate functions (COUNT, SUM, AVG) based on sensitivity and user privacy budgets.
3.  **Database Interface (`db.py`):** A clean abstraction layer for executing raw SQL against PostgreSQL.
4.  **Eco-Scheduler (`eco_scheduler.py`):** Manages the `CodeCarbon` lifecycle to track energy consumption during the "Executing..." state.
5.  **Masking Engine (Internal to `main.py`):** Dynamically redacts PII (Personally Identifiable Information) columns based on an admin-configurable persistent mask list.

---

## 🚀 Implemented Features (V3)

### 1. **Professional CLI Interface**
- **Branded ASCII Banner:** High-resolution multi-color "NOVA QL" logo on startup.
- **70/30 Split Layout:** 
    - **Main Area (70%):** Displays query results, audit logs, and status panels.
    - **Sidebar (30%):** Persistent dashboard showing current role, mode, epsilon, and command cheat-sheet.
- **Autocomplete & History:** SQL keyword and table-name autocompletion with persistent command history across sessions.

### 2. **Multi-Role Authentication**
- **Admin:** Full access to all privacy modes (`raw`, `private`, `audit`), unlimited privacy budget, and exclusive access to PII masking configuration (`\dmc`).
- **Analyst:** Restricted to `private` mode only, limited privacy budget (10.0), and forced PII masking.
- **Auditor:** Access to `private` and `audit` modes, slightly higher budget (15.0), and forced PII masking.

### 3. **Differential Privacy (DP) Engine**
- **Aggregate Detection:** Automatically identifies aggregate queries (COUNT, SUM, AVG) and applies appropriate noise.
- **Laplace Mechanism:** Uses sensitivity-based scaling ($Sensitivity / \epsilon$) to ensure mathematical privacy guarantees.
- **Privacy Budgeting:** Each user has a "budget" that decreases with every private query, preventing privacy exhaustion via repeated queries.
- **Modes:**
    - `private`: Default mode; returns noisy results.
    - `raw`: Admin-only; returns exact database results.
    - `audit`: Returns both noisy results and the exact noise/raw data for transparency/research.

### 4. **Dynamic PII Masking**
- **Persistent Configuration:** Masked columns are stored in `.mask_config.json`.
- **Admin Wizard (`\dmc`):** An interactive tool for admins to browse the database schema and toggle masking on specific columns.
- **Dynamic Redaction:** Non-admin roles see sensitive data (like Aadhar numbers) redacted (e.g., `********1234`).

### 5. **Sustainability & Execution Metrics**
- **CO2 Tracking:** Estimates carbon emissions (in kg) for every individual query execution.
- **Live Metrics Dashboard (`\metrics`):** A comprehensive summary of user activity, average execution time, and total carbon footprint.

---

## 📁 Directory Structure

```text
NOVA - QL - V3/
├── backend/
│   ├── main.py                 # Core CLI & Orchestration Logic
│   ├── privacy.py              # Differential Privacy Engine (Laplace)
│   ├── eco_scheduler.py        # CodeCarbon Wrapper
│   ├── db.py                   # PostgreSQL Interface
│   ├── config.py               # Global Settings (DB & DP)
│   ├── .mask_config.json       # Persistent PII masking settings
│   └── .safe_sql_history       # CLI Command History
├── utils/
│   ├── query_buffer.py         # [Experimental] Queue for query batching
│   └── energy_tracker.py       # [Experimental] Basic energy usage util
├── requirements.txt            # Project Dependencies
└── README.md                   # Public Documentation
```

---

## ⚙️ Setup & Installation

### **1. Prerequisites**
- Python 3.9+
- PostgreSQL Server

### **2. Database Setup**
Ensure you have a database named `Students` (or as configured in `main.py`).
```sql
CREATE DATABASE "Students";
```

### **3. Environment Setup**
```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### **4. Running the App**
```bash
python -m backend.main
```

---

## 🧠 Key Components & Code Flow

### **The Query Lifecycle**
1.  **Input:** User enters SQL in the `prompt_toolkit` session.
2.  **Tracking:** `EcoScheduler` starts the `EmissionsTracker`.
3.  **Execution:** `DatabaseInterface` executes the raw SQL on PostgreSQL.
4.  **Privacy Processing:**
    - If it's an aggregate query, `DifferentialPrivacy` applies Laplace noise.
    - If it's a non-admin role, `apply_masking` redacts PII columns.
5.  **Output:** The result is rendered in a `rich.Table` within the 70/30 split layout, accompanied by execution time and CO2 metrics.

### **Command Reference**
- `\logout`: Switch user/role without exiting the app.
- `\epsilon <val>`: Adjust noise level (Lower = More Privacy).
- `\mode <mode>`: Switch between `private`, `raw`, and `audit`.
- `\dmc`: (Admin Only) Launch the PII Masking Wizard.
- `\metrics`: Show the live performance and privacy dashboard.
- `\help`: Show the full command reference.

---

## ⚠️ Internal Notes & Observations
- **Config Inconsistency:** `main.py` currently contains hardcoded DB credentials at the bottom of the file which override `config.py`. It is recommended to refactor `main.py` to use `backend.config` variables for production.
- **Schema Discovery:** The `\dmc` wizard uses `information_schema.columns` to dynamically discover the database structure, making it compatible with any PostgreSQL schema.
- **Sensitivity Scaling:** `privacy.py` uses fixed sensitivity values (1 for COUNT, 100 for SUM). For advanced research, these should be made dynamic based on column bounds.

# Bayer Horeca Sales Intelligence System

An AI-powered sales analytics and intelligent report generation system designed for Horeca (Hotel/Restaurant/Café) coffee and tea distribution operations.

![System Architecture](SYSTEM%20BUILD%20PLAN.pdf)

## 🌟 Key Features

- **Natural Language Data Assistant:** Interactive chat engine powered by Qwen3 32B (via OpenRouter) that converts natural language business queries into PostgreSQL analytical SQL, executes read-only queries, and returns formatted data summaries, tables, and inline charts.
- **AI-Driven Report Generation Engine:** Interprets natural language instructions in the report description field to dynamically build custom Excel workbooks (`.xlsx`) with custom pivot tables, multi-tab routing, top-N conditional highlighting, KPI summary cards, and embedded charts.
- **Deterministic Excel & PDF Exporters:** Standard 4-tab Excel workbook generation and landscape PDF exports powered by `openpyxl` and `ReportLab`.
- **Interactive Sales Dashboard:** Modern Vite + React UI for filtering sales by date range, route numbers (Routes 1–7), product categories (Coffee, Tea, Others), SKUs, and specific customers.

---

## 🏗️ Project Architecture

```
bayer-s-sales-intelligence/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI application & REST endpoints
│   │   ├── chat.py          # LLM chat engine (Qwen3 32B via OpenRouter)
│   │   ├── reports.py       # OpenPyXL & ReportLab report generation engine
│   │   ├── report_spec.py   # AI report specification generator (JSON ReportSpec)
│   │   └── db.py            # PostgreSQL connection pool manager
│   └── .env                 # Database & API configuration
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.ts    # Fetch API client with RFC 5987 header parsing
│   │   │   └── mock.ts      # Offline mock implementation
│   │   ├── components/
│   │   │   ├── ChatView.tsx    # Natural language query interface
│   │   │   ├── ReportView.tsx  # Interactive report generator UI
│   │   │   └── InlineChart.tsx # Dynamic chart visualizations
│   │   ├── App.tsx          # Main React container
│   │   ├── styles.css       # Custom design system styles
│   │   └── types.ts         # TypeScript definitions
│   ├── vite.config.ts       # Vite dev server & proxy settings
│   └── package.json
└── AGENTS.md
```

---

## 🚀 Quick Start

### Prerequisites

- **Python:** 3.10 or higher
- **Node.js:** v18 or higher
- **Database:** PostgreSQL (with `horeca_sales_db` database initialized)

---

### 1. Backend Setup

```powershell
# Navigate to backend directory
cd backend

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install required Python packages
pip install fastapi uvicorn psycopg2-binary openpyxl reportlab httpx python-dotenv pydantic

# Create / update backend/.env with your database & API keys:
# DB_HOST=localhost
# DB_PORT=5432
# DB_USER=postgres
# DB_PASSWORD=your_password
# DB_NAME=horeca_sales_db
# OPENROUTER_API_KEY=your_openrouter_key

# Start backend server
uvicorn app.main:app --reload --port 8000
```

The FastAPI backend will run at **`http://localhost:8000`** (Swagger docs available at `http://localhost:8000/docs`).

---

### 2. Unified Production & Localhost Run (Single URL)

To run the **entire working project** (frontend dashboard + backend APIs) under a single URL without separate servers:

```powershell
# Build frontend static bundle
cd frontend
npm run build
cd ..

# Start the unified server (or run .\start.bat)
cd backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

The entire working application is now accessible at **`http://localhost:8000`**.

---

### 3. Standalone Frontend Development (Optional)

If developing frontend UI components with Hot Module Replacement (HMR):

```powershell
cd frontend
npm run dev
```

The Vite dev server will run at **`http://localhost:5173`** and proxy `/api` requests to port 8000.

---

## 📊 Report Generation Workflow

1. Select date ranges, routes, branches, and customer filters on the **Generate a Report** tab.
2. Type custom instructions into the **Description / Notes** field (e.g., *"Create a pivot table with Customer in rows and SKU in columns"* or *"Highlight top 10 customers by revenue"*).
3. The system passes your instruction to the AI spec builder, which structures the layout, sorting, pivot tables, and conditional formatting without embedding raw prompt text into your output file.
4. Download the generated `.xlsx` workbook ready to open directly in Microsoft Excel!

---

## 📜 License

Internal Proprietary Project — Bayer Sales Intelligence Initiative.

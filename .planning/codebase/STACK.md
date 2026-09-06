# Technology Stack & Environment

## 1. Core Runtimes & Languages

| Layer | Technology | Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Backend Runtime** | Python | 3.10+ (tested on 3.10/3.11/3.12) | Core API, AI chat, data pipeline, and report generation engines |
| **Frontend Runtime** | Node.js | v18.0.0+ | Development server, module bundling, and client build tooling |
| **Frontend Language**| TypeScript | ^5.9.3 | Type-safe React dashboard and API client implementations |
| **Database Engine**  | PostgreSQL | 14+ / 15+ / 16+ | Relational data store (`horeca_sales_db`) with read-only security gates |

---

## 2. Backend Ecosystem

### Framework & HTTP Server
- **FastAPI (`fastapi`):** Asynchronous REST API framework handling health checks, metadata lookups, chat interactions, and binary report downloads.
- **Uvicorn (`uvicorn`):** Lightning-fast ASGI web server implementation running `app.main:app`.
- **Pydantic (`pydantic`):** Request validation and data parsing for chat requests, report generation parameters, and metadata contracts.

### Database & Analytics Drivers
- **Psycopg2 Binary (`psycopg2-binary`):** PostgreSQL database adapter using `psycopg2.pool.SimpleConnectionPool` with `RealDictCursor` for dictionary result sets.
- **Enforced Read-Only Mode:** Connection pool initializes with `-c default_transaction_read_only=on` to block any write/mutation at the session level.

### Document Compilation & Excel Generation
- **OpenPyXL (`openpyxl`):** Comprehensive spreadsheet generation engine supporting dynamic formulas (`SUM`, `AVERAGE`), cross-tab pivot tables, custom cell styling, XML namespaces, and multi-tab workbooks.
- **ReportLab (`reportlab`):** Landscape PDF rendering engine with tabular styling and page breaking for sales summary documents.

### Networking & AI Integration
- **HTTPX (`httpx`):** Asynchronous HTTP client communicating with OpenRouter for LLM text generation and JSON schema output.
- **Python Dotenv (`python-dotenv`):** Environment configuration loader pulling credentials and database settings from `backend/.env`.
- **SQLGlot (`sqlglot`):** AST SQL parser used in `app.security.sql_validator` to inspect and validate read-only AST structures (with regex fallbacks).

### Testing & Quality Assurance
- **Pytest (`pytest`):** Test execution framework powering the 131-test security suite (`backend/tests/test_security.py`).

---

## 3. Frontend Ecosystem

### Framework & UI Libraries
- **React (`react`, `react-dom`):** ^19.2.0 modern functional React with hooks (`useState`, `useEffect`, `useRef`).
- **Vite (`vite`):** ^7.1.0 ultra-fast module bundler and local development server.
- **@vitejs/plugin-react:** ^5.1.0 Babel/SWC Fast Refresh integration for React components.

### Styling & Design System
- **Pure Vanilla CSS (`frontend/src/styles.css`):** Custom enterprise design system without TailwindCSS or heavy UI frameworks. Features dark-themed aesthetic, curated typography, CSS variables, glassmorphism cards, responsive flex/grid layouts, and micro-animations.

---

## 4. Development & Build Tooling

### Package Managers
- **Backend:** `pip` with virtual environment (`backend/venv/`).
- **Frontend:** `npm` with lockfile `package-lock.json` (`v3` format).

### Key Execution Commands
```powershell
# Backend server startup
cd backend
.\venv\Scripts\activate
uvicorn app.main:app --reload --port 8000

# Backend test suite execution
cd backend
.\venv\Scripts\pytest tests/test_security.py -v

# Frontend development server
cd frontend
npm run dev

# Frontend production build
cd frontend
npm run build
```

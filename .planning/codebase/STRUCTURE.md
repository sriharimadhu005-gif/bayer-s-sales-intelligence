# Directory Layout & File Organization

## 1. Project Directory Tree

```
bayer's sales intelligence/
├── .planning/                              # GSD planning artifacts & codebase maps
│   └── codebase/                           # Structured codebase documentation
│       ├── STACK.md
│       ├── INTEGRATIONS.md
│       ├── ARCHITECTURE.md
│       ├── STRUCTURE.md
│       ├── CONVENTIONS.md
│       ├── TESTING.md
│       └── CONCERNS.md
├── AGENTS.md                               # Project rules, conventions, and document guidelines
├── README.md                               # Project introduction and quick-start instructions
├── Bayar's Project Brief.Solution (7).pdf  # Source project brief & problem statement
├── Enterprise_AI_Architecture_Notes.pdf    # Supporting enterprise architecture notes
├── Sales_Dashboard_Frontend_Requirements.pdf# UI/UX design specifications
├── SYSTEM BUILD PLAN.pdf                   # High-level architecture and build stages
├── final architecture.pdf                  # Target enterprise architecture blueprint
│
├── backend/                                # FastAPI backend service
│   ├── .env                                # Local environment variables (DB credentials, API keys)
│   ├── setup_readonly_user.sql             # SQL script to provision read-only DB role
│   ├── app/                                # Application package
│   │   ├── __init__.py                     # Package marker
│   │   ├── main.py                         # FastAPI routes, CORS, middleware, static mounts
│   │   ├── chat.py                         # LLM chat engine, Qwen3 32B calls, NL-to-SQL logic
│   │   ├── db.py                           # PostgreSQL connection pool (read-only transactions)
│   │   ├── memory.py                       # Conversation memory & structured context manager
│   │   ├── bde_sop.py                      # Canonical BDE Performance Report SOP & OpenPyXL compiler
│   │   ├── reports.py                      # Excel/PDF report generation & OpenPyXL spec runner
│   │   ├── report_spec.py                  # AI ReportSpec generator translating user notes to JSON
│   │   └── security/                       # Defense-in-depth security package
│   │       ├── __init__.py                 # Security package exports
│   │       ├── constants.py                # Regexes, forbidden keywords, safe refusal messages
│   │       ├── prompt_governance.py        # Input screening for prompt injection & role escalation
│   │       ├── sql_validator.py            # AST & regex SQL validation gatekeeper
│   │       └── audit_logger.py             # Security event recording & audit trails
│   ├── tests/                              # Backend test suites
│   │   └── test_security.py                # 131 automated unit & integration security tests
│   └── logs/                               # Runtime log outputs
│
├── frontend/                               # Vite + React + TypeScript frontend
│   ├── package.json                        # Node dependencies & build scripts
│   ├── tsconfig.json                       # TypeScript compiler root config
│   ├── tsconfig.app.json                   # TypeScript compiler application config
│   ├── tsconfig.node.json                  # TypeScript compiler Vite config
│   ├── vite.config.ts                      # Vite configuration & dev proxy
│   ├── index.html                          # Single-page application entry HTML
│   ├── dist/                               # Production build output (served by FastAPI)
│   └── src/                                # Application source code
│       ├── main.tsx                        # React DOM mounting entry point
│       ├── App.tsx                         # App shell, navigation state, layout container
│       ├── styles.css                      # Vanilla CSS design system & component styles
│       ├── types.ts                        # TypeScript interfaces & API payload types
│       ├── api/                            # Client-side API integration
│       │   ├── client.ts                   # Fetch API wrapper with RFC 5987 header parser
│       │   └── mock.ts                     # Mock backend for offline/isolated frontend testing
│       └── components/                     # React UI components
│           ├── ChatView.tsx                # Data assistant chat UI with markdown & table cards
│           ├── ReportView.tsx              # Interactive report builder with filters & download
│           └── InlineChart.tsx             # Interactive SVG-based inline chart visualizer
│
├── docs/                                   # Authoritative project specifications
│   └── report_standards/                   # Canonical BDE report SOPs & references
│       ├── Architecture.md                 # 4-tier decoupled SOP architecture notes
│       ├── BDE_Report.md                   # Canonical SOP for the 7-route BDE performance report
│       ├── BusinessRules.md                # Metric calculations, SLA thresholds, targets
│       ├── FieldMappings.md                # PostgreSQL table-to-metric schema mappings
│       ├── FormattingGuide.md              # Palette colors, border weights, styling rules
│       ├── FormulaReference.md             # Canonical Excel formulas (SUM, AVERAGE, coordinate maps)
│       └── ReportGenerationFlow.md         # End-to-end execution sequence documentation
│
└── tmp/                                    # Local scratch & disposable working files
```

---

## 2. Module Responsibilities & Boundaries

### Backend Core (`backend/app/`)
- **`main.py`:** Public HTTP API surface. Validates inbound REST payloads, maps endpoints, dispatches queries to `chat.py`, `reports.py`, or `bde_sop.py`, and streams binary files to the client.
- **`chat.py`:** Orchestrates the multi-turn conversational AI. Invokes prompt screening, prepares schema context, calls OpenRouter, passes SQL through validation, runs database queries, and formats assistant responses.
- **`db.py`:** Encapsulates the `psycopg2` connection pool. Enforces read-only sessions and executes validated queries.
- **`memory.py`:** In-memory store maintaining conversation histories, token counts, compressed summaries, and ephemeral report download caches.
- **`reports.py`:** Low-level spreadsheet and PDF builder. Implements both standard 4-tab workbooks and dynamic spec-driven layouts from `ReportSpec` models.
- **`report_spec.py`:** Prompt engineer converting natural language reporting instructions into structured JSON schemas specifying worksheets, columns, grouping, and styling.
- **`bde_sop.py`:** Authoritative SOP implementation that reads markdown standards from `docs/report_standards/` and compiles the canonical BDE performance workbook using dynamic OpenPyXL formulas.

### Security Module (`backend/app/security/`)
- **`prompt_governance.py`:** Gatekeeper scanning user prompts for injection patterns, jailbreaks, system prompt extractions, and administrative overrides.
- **`sql_validator.py`:** Gatekeeper inspecting SQL statements using AST parsing (`sqlglot`) and regex checks to reject mutations, multi-statement payloads, or dangerous Postgres functions.
- **`audit_logger.py`:** Appends security-relevant events to log files for compliance and auditability.
- **`constants.py`:** Centralized catalog of forbidden keywords, SQL tokens, and standard refusal messages.

### Frontend Module (`frontend/src/`)
- **`App.tsx`:** Primary layout host providing the collapsible sidebar, route views (`chat` vs. `report`), and global prefill state handoff.
- **`components/ChatView.tsx`:** Handles message streams, prompt submissions, conversation reset, markdown rendering, tabular previews, and one-click "Open in Report Builder" transitions.
- **`components/ReportView.tsx`:** Multi-filter control panel (dates, routes, branches, SKUs, customers), format selector (Excel/PDF), natural language notes input, and download trigger.
- **`components/InlineChart.tsx`:** Lightweight SVG chart renderer (supporting `bar`, `line`, and `pie`) embedded directly into chat responses.
- **`api/client.ts`:** Real network client interfacing with FastAPI endpoints. Handles streaming file downloads, response error decoding, and RFC 5987 header parsing.
- **`api/mock.ts`:** Standalone mock client providing realistic mock data and simulated report downloads when the backend is offline.

### Canonical SOP Documentation (`docs/report_standards/`)
- Acts as the single source of truth for all BDE report logic. Files are read dynamically by `bde_sop.py` to ensure documentation and runtime behavior remain perfectly synchronized.

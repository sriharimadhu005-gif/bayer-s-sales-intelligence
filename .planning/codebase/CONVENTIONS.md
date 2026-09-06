# Coding Standards & Conventions

## 1. Python & Backend Standards

### Language Level & Typing
- **Python 3.10+ Native Syntax:** Use modern union types (`str | None`, `int | float`), parameterized generics (`list[dict]`, `dict[str, Any]`), and structural pattern matching where applicable.
- **Strict Type Hinting:** Function parameters, return signatures, and public module variables must include explicit type annotations.
- **Data Containers:** Prefer `@dataclass` for internal state containers (e.g., `ConversationMessage`, `StructuredState`, `ValidationResult`, `GovernanceResult`) and `pydantic.BaseModel` for external API request payloads (`ChatRequest`, `ReportRequest`).

### Code Formatting & Structure
- **Indentation:** 4 spaces across all `.py` files (no tabs).
- **Section Dividers:** Code blocks and logical groups are organized using ASCII comment banners:
  ```python
  # ═══════════════════════════════════════════════════════════════════════
  # Section Name
  # ═══════════════════════════════════════════════════════════════════════
  ```
- **Docstrings:** All modules, classes, and public functions require docstrings formatted in Google or NumPy docstring convention specifying parameters, return types, and exceptions.

### Defensive Engineering & Error Handling
- **Graceful Fallbacks:** External dependencies and complex parsers must include fallback mechanisms. For example, `sql_validator.py` attempts an AST parse via `sqlglot`, but falls back to strict regex validation if `sqlglot` is unavailable.
- **Custom Exceptions:** Domain-specific errors raise explicit exception classes (e.g., `ReadOnlyViolationError`) rather than generic `RuntimeError` or `Exception`.
- **Fail-Closed Security:** Security validators default to rejecting queries (`is_valid = False`, `is_safe = False`) upon encountering unexpected parse exceptions or unrecognized keywords.

### Database & SQL Conventions
- **Read-Only Invariant:** All queries must be strictly `SELECT` or `WITH ... SELECT`. No `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, or transactional statements are permitted.
- **Parameterization:** Queries with user-supplied arguments must use parameterized query placeholders (`%s` with `psycopg2`) rather than string concatenation or formatted f-strings.
- **Column Aliasing:** SQL queries should explicitly alias calculated metrics to match expected dictionary keys (e.g., `SUM(qty_kg) AS total_kg`, `SUM(estimated_revenue) AS total_revenue`).

---

## 2. Frontend & TypeScript Standards

### Component & File Conventions
- **Functional Components:** All React components use functional component declarations with explicit TypeScript interfaces for props:
  ```typescript
  interface ChatViewProps {
    onGenerateReport: (prefill: ReportPrefill) => void
  }
  export function ChatView({ onGenerateReport }: ChatViewProps) { ... }
  ```
- **File Organization:** One primary component per file matching the component name (e.g., `ChatView.tsx`, `ReportView.tsx`).
- **Shared Types:** API contracts, domain entities, and data structures are centralized in `frontend/src/types.ts`.

### Styling & CSS Design System
- **Pure Vanilla CSS:** Avoid utility-first CSS frameworks (such as TailwindCSS) or heavy third-party UI component libraries (such as MUI or AntD).
- **CSS Variables:** Theming is governed entirely through custom properties defined on `:root` in `frontend/src/styles.css`:
  - Surfaces: `--bg-canvas`, `--bg-card`, `--bg-elevated`
  - Typography: `--text-primary`, `--text-secondary`, `--text-muted`
  - Accents: `--accent`, `--accent-hover`, `--accent-subtle`
  - Borders: `--border-subtle`, `--border-strong`
- **Responsive Design:** Interfaces utilize flexible CSS Grid and Flexbox layouts without hardcoded viewport pixel constraints.

### Networking & API Standards
- **Fetch Abstraction:** Client network calls are centralized in `frontend/src/api/client.ts`.
- **RFC 5987 Header Parsing:** Binary file download endpoints extract filenames using RFC 5987 compliant regex parsing (`filename*=UTF-8''...` and `filename="..."`) to support localized or special characters.
- **Offline Mock Support:** `frontend/src/api/mock.ts` must maintain interface parity with `client.ts` to allow frontend development and testing in isolated environments.

---

## 3. Documentation & Repository Conventions

### Markdown & Document Standards (per `AGENTS.md`)
- **Tone:** Professional, objective English tailored for technical and commercial executive stakeholders.
- **Headings & Titles:** Title Case for main document titles (`# System Architecture & Design Patterns`), sentence case for subheadings (`## 1. Architectural overview`), ASCII hyphens for lists and dividers.
- **Working Files:** Ephemeral data, scripts, and temporary renderings belong strictly in `tmp/` and must never be committed to repository history.
- **Acronym Consistency:** Define acronyms upon first usage (e.g., *Business Development Executive (BDE)*, *Stock Keeping Unit (SKU)*).

# Formatting & Styling Guide: BDE Performance Report

## Document Control
- **Document ID:** FG-BDE-001
- **Associated SOP:** SOP-BDE-001 (`BDE_Report.md`)
- **Canonical Specification Source:** `4.BDE Report.xlsx`
- **Application:** Excel Generation Engine, OpenPyXL Styler, UI Preview

---

## 1. Column Widths & Margins

Column A is an unmerged spacer column creating an intentional left margin. Columns B through L host all report content.

| Column | Column Letter | Target Width | Primary Content / Field Usage |
| :---: | :---: | :---: | :--- |
| 1 | **A** | `9.14` | Left margin spacer (always blank) |
| 2 | **B** | `18.00` | Section labels, Route numbers ($1 \dots 7$), `"TOTAL"` |
| 3 | **C** | `16.71` | Prev Month Count, Coffee Target, Target Regain Customers |
| 4 | **D** | `13.14` | Current Month Count, Coffee Achieved, Regain Achieved |
| 5 | **E** | `11.71` | Retention %, Coffee Balance, Regain Balance |
| 6 | **F** | `11.57` | Retention Balance, Tea Target, Section 3 spacer |
| 7 | **G** | `10.71` | Section 1 spacer, Tea Achieved, Target Customers in nos |
| 8 | **H** | `13.71` | Overdue Target, Tea Balance, Target Qty (KG) |
| 9 | **I** | `13.29` | Overdue Current, Combined Target, Achieved Customers in nos |
| 10 | **J** | `12.86` | Overdue Balance, Combined Achieved, Achieved Qty (KG) |
| 11 | **K** | `12.57` | Combined Balance, Balance in Nos |
| 12 | **L** | `9.29` | Combined Volume %, Balance in Kgs |

---

## 2. Row Heights & Typography

- **Default Font:** `Calibri`, regular, 11pt across all data cells.
- **Section Headers & Titles:** `Calibri`, bold, 11pt.
- **Title Block (B1):** `Calibri`, bold, 11pt, left-aligned.
- **Row Heights:**
  - **Row 1:** 15.0 pt
  - **Row 3 (Major Headers):** 15.0 pt
  - **Row 4 (Section 1 Subheaders):** `30.0 pt` (accommodates wrapped headers)
  - **Rows 5–12 (Section 1 Data & Totals):** `14.5 pt`
  - **Rows 15–16 (Section 2 Headers):** `15.0 pt`
  - **Rows 17–24 (Section 2 Data & Totals):** `14.5 pt`
  - **Row 27 (Section 3 Major Headers):** `15.0 pt`
  - **Row 28 (Section 3 Subheaders):** `45.0 pt` (accommodates multi-line column descriptions)
  - **Rows 29–36 (Section 3 Data & Totals):** `14.5 pt`

---

## 3. Merged Cell Ranges

The canonical workbook defines exactly 10 merged cell ranges:

```python
CANONICAL_MERGED_RANGES = [
    # Section 1: Retention & Overdue
    "B3:B4",    # BDE Route Nos (vertical merge across header rows)
    "C3:F3",    # Retention (spanning Prev, Curr, %, Balance)
    "H3:J3",    # Outstanding Over Due Report (spanning Target, Current, Balance)
    
    # Section 2: Volume Performance
    "B15:B16",  # BDE Route Nos (vertical merge across header rows)
    "C15:E15",  # Coffee (spanning Target, Achieved, Balance)
    "F15:H15",  # Tea (spanning Target, Achieved, Balance)
    "I15:L15",  # TOTAL (spanning Target, Achieved, Balance, %)
    
    # Section 3: Customer Acquisition
    "B27:B28",  # BDE Route Nos (vertical merge across header rows)
    "C27:E27",  # Regain (spanning Target, Achieved, Balance)
    "G27:L27",  # New Customers (spanning TargetNos, TargetKg, AchNos, AchKg, BalNos, BalKg)
]
```

---

## 4. Palette, Fills & Borders

### 4.1 Theme Palette
1. **Section 1 Accent Highlight (Retention & Overdue):**
   - The canonical template applies a soft pastel accent fill to highlight Section 1:
   - **Fill Type:** `solid`
   - **Color Value:** Soft Sage / Light Olive Accent (Hex `#E2EFDA` or Theme Accent 3 tint +80% `#C6E0B4`).
   - **Applied Range:** `C3:F12` (Retention block) and `H3:J12` (Overdue block).
2. **Section 2 & 3 Standard Grid:**
   - **Fill Type:** Clean white (`#FFFFFF`) / None.
   - Headers use clear bold text on white background with crisp gridlines.

### 4.2 Border Styling
- **Gridlines:** All tabular data cells in Sections 1, 2, and 3 have thin solid borders on all four sides (`thin`, color `#D9D9D9` or standard Excel automatic border).
- **Separators:** Rows 13–14 and 25–26 have no borders and act as white-space section dividers.

---

## 5. Number Formatting Specifications

| Field Category | Target Excel Format Code | Display Example |
| :--- | :--- | :--- |
| **Retention Percentage** | `0.00%` | `80.37%` |
| **Volume Achievement Percentage** | `0%` | `94%` |
| **Financial / Currency (Overdue)** | `_ * #,##0_ ;_ * \-#,##0_ ;_ * "-"??_ ;_ @_` | ` 350,000 ` or ` -350,000 ` |
| **Customer Counts (Nos)** | `General` or `#,##0` | `236` |
| **Product Volume (KG)** | `#,##0.0` or `0` | `9,387` or `7,732.3` |

---

## 6. Production OpenPyXL Assembly Code

The following Python function generates a pixel-perfect BDE Performance Report worksheet matching the canonical specification:

```python
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

def format_bde_worksheet(ws: openpyxl.worksheet.worksheet.Worksheet):
    """Applies canonical typography, fills, borders, alignments, and widths."""
    
    # 1. Set Column Widths
    col_widths = {
        'A': 9.14, 'B': 18.00, 'C': 16.71, 'D': 13.14, 'E': 11.71, 'F': 11.57,
        'G': 10.71, 'H': 13.71, 'I': 13.29, 'J': 12.86, 'K': 12.57, 'L': 9.29
    }
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width

    # 2. Set Row Heights
    ws.row_dimensions[4].height = 30.0
    ws.row_dimensions[28].height = 45.0
    for r in list(range(5, 13)) + list(range(17, 25)) + list(range(29, 37)):
        ws.row_dimensions[r].height = 14.5

    # 3. Apply Merges
    merges = [
        "B3:B4", "C3:F3", "H3:J3",
        "B15:B16", "C15:E15", "F15:H15", "I15:L15",
        "B27:B28", "C27:E27", "G27:L27"
    ]
    for m in merges:
        ws.merge_cells(m)

    # 4. Define Styles
    font_bold = Font(name="Calibri", size=11, bold=True)
    font_regular = Font(name="Calibri", size=11, bold=False)
    fill_section1 = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    
    thin_side = Side(border_style="thin", color="000000")
    cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    
    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_right = Alignment(horizontal="right", vertical="center")

    # 5. Apply Fills, Borders & Alignment to Section 1 (Rows 3-12)
    for r in range(3, 13):
        for col_idx in [2, 3, 4, 5, 6, 8, 9, 10]:
            c = ws.cell(r, col_idx)
            c.border = cell_border
            c.alignment = align_center
            if col_idx in [3, 4, 5, 6, 8, 9, 10]:
                c.fill = fill_section1
            if r in [3, 4, 12]:
                c.font = font_bold

    # 6. Apply Borders & Alignment to Section 2 (Rows 15-24)
    for r in range(15, 25):
        for col_idx in range(2, 13):
            c = ws.cell(r, col_idx)
            c.border = cell_border
            c.alignment = align_center
            if r in [15, 16, 24]:
                c.font = font_bold

    # 7. Apply Borders & Alignment to Section 3 (Rows 27-36)
    for r in range(27, 37):
        for col_idx in [2, 3, 4, 5, 7, 8, 9, 10, 11, 12]:
            c = ws.cell(r, col_idx)
            c.border = cell_border
            c.alignment = align_center
            if r in [27, 28, 36]:
                c.font = font_bold

    # 8. Number Formatting
    # Section 1 Retention %
    for r in range(5, 13):
        ws.cell(r, 5).number_format = "0.00%"
        ws.cell(r, 8).number_format = '_ * #,##0_ ;_ * \-#,##0_ ;_ * "-"??_ ;_ @_'
        ws.cell(r, 9).number_format = '_ * #,##0_ ;_ * \-#,##0_ ;_ * "-"??_ ;_ @_'
        ws.cell(r, 10).number_format = '_ * #,##0_ ;_ * \-#,##0_ ;_ * "-"??_ ;_ @_'

    # Section 2 Volume %
    for r in range(17, 25):
        ws.cell(r, 12).number_format = "0%"

    # Gridlines visibility
    ws.views.sheetView[0].showGridLines = True
```

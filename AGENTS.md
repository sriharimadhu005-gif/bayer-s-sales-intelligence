# Repository Guidelines

## Project Structure & Module Organization

This repository contains the planning and reference material for the Bayer Sales Intelligence initiative. The repository root holds the primary PDF deliverables:

- `Bayar's Project Brief.Solution (7).pdf` - source project brief and solution context.
- `Bayer_Sales_Intelligence_System_Plan.pdf` - proposed system plan.
- `Enterprise_AI_Architecture_Notes.pdf` - supporting architecture notes.
- `tmp/` - local, disposable working files. Do not treat its contents as final deliverables.

Keep final documents in the root unless the project adopts an `output/` directory. Use clear, stable filenames such as `Bayer_Sales_Intelligence_System_Plan_v2.pdf`; avoid vague names such as `final.pdf`.

## Document Development & Validation

There is no application build or automated test suite in this repository. Review changes by opening the PDF and checking that page breaks, headings, tables, diagrams, and links render correctly. For command-line validation where Poppler is available, use:

```powershell
pdfinfo "Bayer_Sales_Intelligence_System_Plan.pdf"
pdftoppm -png "Bayer_Sales_Intelligence_System_Plan.pdf" tmp/plan-page
```

Use `pdfinfo` to confirm basic metadata and page count; inspect the generated PNGs for visual defects. Keep temporary renderings under `tmp/` and do not commit them.

## Content, Style & Naming Conventions

Write in concise, professional English suitable for business and technical stakeholders. Use consistent title casing for document titles, sentence case for section headings, and ASCII hyphens. Define acronyms on first use and keep terminology consistent across all documents (for example, use either "Sales Intelligence System" or its approved acronym throughout).

Preserve source filenames and spelling unless a rename is deliberate and reflected in links or references. Use descriptive names for new files and retain version history only when it serves review or approval needs.

## Review Guidelines

Before sharing an updated PDF, verify factual consistency with the project brief, readable diagrams and tables, correct page numbering, and no clipped or overlapping text. Record substantive assumptions, data sources, and open decisions in the relevant document.

## Commit & Pull Request Guidelines

No Git history is currently available, so use short imperative commit subjects: `docs: update sales intelligence architecture`. Keep each commit focused on one document or review change. Pull requests should identify the changed files, summarize business impact, link the relevant issue or decision, and include screenshots for material layout or diagram changes.

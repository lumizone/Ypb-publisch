Developer Handoff Specification
Label Replication System — Phase 1
1. Objective

Build a deterministic backend-driven system that takes a designer-created Adobe Illustrator label file and automatically generates new labels by replacing three predefined text fields for multiple products.

The system must not modify layout, styling, or compliance content.

2. Functional Requirements
2.1 Inputs
A. Label Template

File types:

.AI (preferred)

.SVG (exported from Illustrator)

.PDF (vector-based only)

Template must contain exactly three replaceable text fields:

product_name

ingredients

sku

Text fields must be identifiable via:

Layer names (AI)

IDs (SVG)

Tagged text objects (PDF)

All other elements are static and immutable.

B. Product Data

Source:

Google Sheets (via API)

CSV upload

Required columns:

product_name

ingredients

sku

Each row = one output label

3. Output Requirements

For each product:

Generate:

High-resolution PNG (300 DPI)

Vector PDF

SVG (optional if supported by input format)

File naming convention:

{product_name}_{sku}.{ext}


Batch output:

ZIP archive:

/labels/
  product1_sku.pdf
  product1_sku.png
  product2_sku.pdf
  product2_sku.png

4. Core System Components
4.1 Template Parser

Responsibilities:

Load vector file

Detect required placeholders

Validate:

All three fields exist

No duplicates

Fail fast if validation fails

Errors:

Missing placeholder

Duplicate placeholder

Unsupported format

4.2 Data Mapper

Responsibilities:

Map product row → template fields

Replace text values only

Preserve:

font family

font size

kerning

color

alignment

line breaks

No layout recalculation allowed.

4.3 Renderer / Export Engine

Responsibilities:

Render vector output deterministically

Produce:

PDF (vector preserved)

PNG (300 DPI)

No rasterization of vector PDFs

4.4 Batch Processor

Responsibilities:

Iterate over product rows

Generate one label per row

Control concurrency

Prevent partial batch failure

If one SKU fails → log error → continue batch.

4.5 Packaging Module

Responsibilities:

Organize output files

Compress into ZIP

Optional:

Upload ZIP to Dropbox

5. UI Requirements (Internal Use)

Minimal admin UI:

Upload label template

Upload CSV or connect Google Sheet

Validate template

Start batch generation

Download ZIP

No client-facing UX required.

6. Non-Functional Requirements
Performance

Batch size: 60–100+ labels

Target runtime:

< 2 minutes per batch

Security

No persistent storage of client assets

Temporary files auto-purged

Reliability

Deterministic output

No AI or probabilistic logic

7. Constraints & Assumptions

Text must fit predefined bounding boxes

No dynamic resizing

No font substitution

Fonts must be embedded or available server-side

Compliance text is static and untouchable

Overflow text is designer responsibility.

8. Technology Notes (Suggested, Not Mandated)

Vector processing:

SVG preferred internally

AI/PDF converted to SVG if needed

Rendering:

Headless vector renderer

Backend:

Node.js / Python

Storage:

Temporary FS + optional Dropbox API

9. Error Handling
Error	Action
Missing placeholder	Reject template
Invalid CSV	Reject batch
Render failure	Skip SKU, log error
Export failure	Retry once, then fail
10. Acceptance Criteria

The system is accepted when:

One Illustrator template generates correct labels for all SKUs

All outputs match original design except text values

No compliance text can be altered

Batch ZIP is production-ready

Manual label duplication is eliminated

11. Out of Scope (Explicit)

Label editor

Design tooling

AI-generated content

Client-facing workflows

Manual per-label adjustments

Versioning

12. Deliverables

Backend service

Minimal admin UI

Documentation

Deployment instructions

13. Summary

This system is a production automation engine, not a design platform.

Its only responsibility is to replicate an approved Illustrator label at scale by replacing three controlled text fields with catalog data—accurately, deterministically, and safely.
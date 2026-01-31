Technical Documentation
Label Replication System – Phase 1
1. System Purpose

The purpose of this system is to automatically replicate product labels at scale using a designer-approved Adobe Illustrator label file.

The system does not create or edit designs.
It reuses an existing, finalized label layout and programmatically generates new labels by replacing text-only fields for additional products.

This eliminates manual duplication work while preserving full designer control.

2. Core Concept

A designer creates a final label design in Adobe Illustrator.

The design includes three dynamic text fields only:

Product Name

Ingredients (or Composition)

SKU

The designer exports the file and uploads it to the application.

The application:

Locks the layout

Replaces only the defined text fields

Generates new labels for additional products

Each output label is production-ready and visually identical except for mapped text values.

3. Input Requirements
3.1 Label Template (Adobe Illustrator)

The designer must provide a fully finalized label file created in Adobe Illustrator.

Supported formats:

.AI (preferred)

.SVG (exported from Illustrator)

.PDF (vector-based)

Template rules:

All layout, fonts, colors, and spacing are final

No resizing or repositioning is allowed by the system

The file must contain exactly three replaceable text layers

Required Text Fields

Each dynamic field must be clearly identifiable using one of the following methods:

Layer names

Text tags/placeholders

IDs (SVG)

Required fields:

product_name

ingredients

sku

All other elements are treated as static and locked.

3.2 Product Data Source

Product data is provided as:

Google Sheets or

CSV file

Each row represents one product.

Required columns:

product_name

ingredients

sku

Optional columns may exist but are ignored unless explicitly mapped.

4. System Responsibilities
4.1 Template Parsing

Load the Illustrator-based template

Identify the three dynamic text fields

Validate that all required placeholders exist

Reject the file if fields are missing or duplicated

4.2 Data Mapping

For each product row:

Replace product_name

Replace ingredients

Replace sku

Preserve:

font

size

color

alignment

text wrapping rules

No layout calculations or AI inference is performed.

4.3 Label Generation

For each product:

Generate a new label file using the original design

Output formats:

Print-ready PNG (high DPI)

Vector PDF

SVG (optional, if source allows)

Each generated label is:

deterministic

visually consistent

compliance-safe

4.4 Batch Processing

One template → N products

Typical batch size:

60–100+ SKUs

Processing occurs sequentially or in controlled parallel batches

4.5 Export & Packaging

Generated files are organized as:

/labels/
  product-name_sku.png
  product-name_sku.pdf


All outputs are packaged into a single ZIP archive

Optional automatic upload to Dropbox

5. System Architecture (High Level)
Frontend

Minimal internal UI

Upload template

Upload or link data source

Start batch generation

Download ZIP

Backend

Vector file parser

Text replacement engine

Export renderer

Batch processor

Storage

Temporary processing storage

Optional Dropbox integration for input/output

6. What the System Does NOT Do

No label design

No layout editing

No font changes

No resizing logic

No AI text generation

No client-facing editor

No version history

No per-label manual editing workflow

This is not a design tool.

7. Constraints & Assumptions

The designer is responsible for:

correct layout

overflow-safe text areas

font embedding

Text must fit within predefined bounds

The system assumes all provided data is valid

If text overflows, it is considered a template design issue, not a system error.

8. Phase 1 Success Criteria

Phase 1 is considered complete when:

A single Illustrator label can generate labels for all SKUs

All generated labels are visually consistent

No compliance text can be altered

Output files are production-ready

Manual label duplication is fully eliminated

9. Summary

This system is a deterministic label replication engine.

It takes:

one designer-approved Illustrator file

one product data table

And produces:

a complete, ready-to-use label set for all products
with zero design changes and zero manual repetition.
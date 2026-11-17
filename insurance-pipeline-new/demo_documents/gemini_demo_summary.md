# Live Gemini demo results

Model: `gemini-3.1-flash-lite`. Synthetic content only.

The PDFs contain selectable synthetic text. Page text is extracted with PyMuPDF; no OCR is needed for these text-based fixtures.

The exact prompt strings, response JSON Schemas, parsed Gemini responses for every call, application results, source evidence, validation results, and ground-truth comparisons are in [gemini_demo_results.json](gemini_demo_results.json).

## Policy Document

PDF: [synthetic_health_policy_schedule.pdf](synthetic_health_policy_schedule.pdf)

Classification: `policy_document` / `accepted` (subtype `schedule`).
Application validation: `passed`; reasons: none.
Ground-truth matches: **9/9** expected fields.

| Field | Extracted raw value | Normalized value | Evidence quote | Ground truth |
|---|---|---|---|---|
| `insurer` | Example Shield Assurance Ltd | Example Shield Assurance Ltd | p1: Example Shield Assurance Ltd | match |
| `product_name` | Example Health Secure | Example Health Secure | p1: Product: Example Health Secure | match |
| `policy_number` | DEMO-POL-2048 | DEMO-POL-2048 | p1: Policy Number: DEMO-POL-2048 | match |
| `policyholder_name` | Alex Demo | Alex Demo | p2: Policyholder: Alex Demo | match |
| `insured_member_name` | Alex Demo | Alex Demo | p2: Insured Member: Alex Demo | match |
| `coverage_start` | 2025-01-01 | 2025-01-01 | p2: Coverage Start: 2025-01-01 | match |
| `coverage_end` | 2025-12-31 | 2025-12-31 | p2: Coverage End: 2025-12-31 | match |
| `sum_insured` | 500000 | 500000 | p2: Sum Insured: INR 500000 | match |
| `currency` | INR | INR | p2: Currency: INR | match |

## Hospital Bill

PDF: [synthetic_hospital_bill.pdf](synthetic_hospital_bill.pdf)

Classification: `hospital_bill` / `accepted` (subtype `none`).
Application validation: `passed`; reasons: none.
Ground-truth matches: **12/12** expected fields.

| Field | Extracted raw value | Normalized value | Evidence quote | Ground truth |
|---|---|---|---|---|
| `hospital_name` | DEMO CITY HOSPITAL | DEMO CITY HOSPITAL | p1: DEMO CITY HOSPITAL | match |
| `invoice_number` | DCH-DEMO-0841 | DCH-DEMO-0841 | p1: Invoice Number: DCH-DEMO-0841 | match |
| `invoice_date` | 2025-02-17 | 2025-02-17 | p1: Invoice Date: 2025-02-17 | match |
| `patient_name` | Alex Demo | Alex Demo | p1: Patient Name: Alex Demo | match |
| `admission_date` | 2025-02-14 | 2025-02-14 | p1: Admission Date: 2025-02-14 | match |
| `discharge_date` | 2025-02-16 | 2025-02-16 | p1: Discharge Date: 2025-02-16 | match |
| `item_description` | Room and nursing charges | Room and nursing charges | p1: Room and nursing charges: INR 12000.00 | not in fixture comparison |
| `item_amount` | 12000.00 | 12000.00 | p1: Room and nursing charges: INR 12000.00 | not in fixture comparison |
| `item_description` | Medical services | Medical services | p1: Medical services: INR 8000.00 | not in fixture comparison |
| `item_amount` | 8000.00 | 8000.00 | p1: Medical services: INR 8000.00 | not in fixture comparison |
| `subtotal` | 20000.00 | 20000.00 | p1: Subtotal: INR 20000.00 | match |
| `taxes` | 0.00 | 0.00 | p1: Taxes: INR 0.00 | match |
| `discount` | 500.00 | 500.00 | p1: Discount: INR 500.00 | match |
| `total` | 19500.00 | 19500.00 | p1: Total: INR 19500.00 | match |
| `currency` | INR | INR | p1: Currency: INR | match |
| `payment_status` | Unpaid | Unpaid | p1: Payment Status: Unpaid | match |

Arithmetic check: INR 20,000.00 subtotal + INR 0.00 taxes - INR 500.00 discount = INR 19,500.00 total; extraction validation passed.

## Scope and limits

These are synthetic, selectable-text PDFs. PyMuPDF extracted their page text, which was sent to the live classifier and document-specific extractor; the application extraction validator then checked field names, source quotes, dates, monetary values, page references, and applicable consistency. This demo did not use OCR, upload storage, database persistence, or the frontend. It covers two synthetic fixtures and is not a general model-accuracy evaluation.

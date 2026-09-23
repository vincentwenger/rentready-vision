# Step 30 — Rental preparation checklist

## Result

Step 30 automatically converts every final verified issue into a concise task
in the **Rental Preparation Checklist**. It uses the existing Step-25 severity
classification to place each task in exactly one section:

- **FIX BEFORE RENTING**
- **REVIEW**
- **COSMETIC**

The checklist is derived from `issues`, the consolidated and classified public
issue collection. Raw frame detections and unverified candidates never become
tasks.

## Status tracking

Every task defaults to **Open** and permits exactly three statuses:

- **Open**
- **In progress**
- **Resolved**

The browser displays an unchecked box for Open and In progress, and a checked
box for Resolved. A status change is persisted on the inspection by `issue_id`
through:

```text
PATCH /inspections/{inspection_id}/checklist/items/{issue_id}
```

The request body contains only the new status. The endpoint rejects any status
outside the three-value contract and rejects issue IDs that are not present in
the verified checklist.

## Scope boundary

This step deliberately does not add contractor management. There are no
contractors, assignees, bids, invoices, work orders, or scheduling fields.

## Verification

Run:

```bash
pytest -q tests/test_step30_repair_checklist.py
python scripts/verify_step30_repair_checklist.py
pytest -q
```

Evidence is stored in `evaluation/step30/`. Local verification covers the
requested example tasks, three-section mapping, status defaults and updates,
verified-issue-only sourcing, browser controls, persistence API, input
immutability, and the contractor-management exclusion.

Live AWS validation is not required for Step 30. The new deterministic
checklist is built from the already validated issue report, and its only write
uses the existing DynamoDB inspection metadata update path.

# RentReady Vision - External v3 Holdout

## STATUS: FROZEN

This directory contains the frozen external v3 holdout.

Video count: 14
Clean / negative: 8
Positive / defect: 6

The files were copied from evaluation/external_v3_candidates and verified
with SHA-256 during the freeze operation.

## Holdout rules

After this freeze:

- Do not add videos.
- Do not delete videos.
- Do not replace videos.
- Do not change labels because of model output.
- Do not tune RentReady Vision using results from this holdout.
- Do not tune thresholds, prompts, frame selection, or detector logic against it.
- Any material change requires a new holdout version.

The intent is to preserve this dataset as genuinely unseen evaluation material.

## Before freeze

No RentReady Vision processing was performed on these holdout videos.

## Integrity

See manifest.json for each video's SHA-256 hash and source metadata.

# Step 34B development milestone — 2026-09-29

Scope: 21 development clips from the Compass and Quimby houses in `evaluation/v3` (8 positive clips, 13 clean clips, 9 annotated visibility intervals). Mozart house was not used to select, tune, or score the candidate.

## Decision

The agreed short-term development milestone of at least 20% **owner-verified interval recall** was met by the experimental candidate-triggered crack fallback: **2/9 = 22.2%**. The owner previously confirmed the Nova candidate's refined vanity mounting box and on 2026-09-29 confirmed that the new refined bathtub box contains enough of the real crack. The candidate is an **offline replay of saved model outputs**, not an integrated production pipeline or a fresh conditional live run. It should remain experimental until the cost tradeoff and behavior on additional clean fixtures are accepted.

| Development measure | Frozen Nova reference | Experimental conditional fallback replay |
| --- | ---: | ---: |
| Owner-verified intervals | 1/9 (11.1%) | 2/9 (22.2%) |
| Verified positive clips | 1/8 | 2/8 |
| Clean clips with false positives | 0/13 | 0/13 |
| Unmatched reported issues | 1 | 1 |
| Verified issue precision against annotations | 1/2 (50%) | 2/3 (66.7%) |
| Clip-presence true positives | 2/8 | 3/8 |
| Model requests | 21 | 40 projected conditional requests |
| Input tokens | 59,577 | 184,293 projected conditional tokens |
| Output tokens | 740 | 1,546 projected conditional tokens |
| OpenCV processing | 86.869 s | 87.005 s replay |
| Model time | 41.608 s | 92.656 s projected from per-clip calls |
| Agent tool calls | 0 | 0 |
| Model dollars | Not measured | Not measured |

The fallback uses the frozen Nova five-view candidate first. For the 19 clips with no accepted Nova issue, it replays the independently measured Sonnet 4.5 result on the same selected frame and views. A reported small crack triggers a source-frame OpenCV dark-line localization step. On the bathtub clip, the initial two crack proposals were checked without using annotation coordinates: one had no coherent nearby line and was dropped; the other was refined to pixel box `[471, 1418, 585, 1479]` on the 1080×1920 frame at 2.0 seconds. The owner confirmed this box contains enough of the annotated crack. The prior owner-confirmed vanity box is retained from the frozen Nova candidate. One drywall-patch finding remains unmatched against its annotation. All 13 clean clips remained negative in the replay.

The extra 19 Sonnet requests and their token/time totals are **counterfactual replay accounting** from an independently executed 21-clip Sonnet experiment. That experiment actually made all 21 Sonnet requests. The conditional 40-request route has not yet been executed end to end and may differ on a later model invocation. Inputs and outputs were cached only for the development clips. There is no dollar estimate because no pricing was supplied. Its input-token total is about 3.09 times the frozen reference, so this is not a free recall improvement.

The alternative Sonnet-only 21-request trial did not beat the reference for clip presence, lost the verified vanity finding, consumed 137,844 input tokens, and produced a bathtub box that an automatic IoU threshold counted although it covered only the right edge of the crack. Owner review was therefore required; the automatic 1/9 Sonnet match was not accepted as a correctly located issue.

## Follow-up

Step 34C measured the fixed development results in `STEP34C_DEVELOPMENT_METRICS.md`. Step 34D builds and validates a callable conditional detector before a configuration freeze; see `STEP34D_DETECTOR_V2_FREEZE.md`. The recorded 2/9 remains an offline replay result until the live route is measured and its boxes reviewed.

Evidence: `comparison_crack_fallback.json`, `spatial_crack_fallback.json`, the individual detector reports in `step34b-crack-fallback-run-20260929`, and the owner's visual confirmation of the retained bathtub box in this conversation. The code is in `Step34B_crack_fallback_replay.zip`; its two focused tests passed on the user's machine. The output directory and paths above refer to the user's local Windows workspace.

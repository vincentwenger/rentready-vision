# Step 59 - Temporary public judging mode

## Result and scope

The temporary public-mode toggle, 500 MB limit, automatic expiry, adjustable quota,
and operator controls were deployed and rehearsed on 2026-10-11. A token-free inspection
completed through its report, video viewer, and persisted checklist. Public access was
left OFF after live expiry and access checks. Git publication and the final judging
window are separate handoff actions; this document does not claim judges have visited.
The existing Step 59 bounding-box fix stays intact. No detector, worker artifact,
AI model, readiness scoring, or report grouping was changed by this extension.

The operator token remains configured and valid. Public access starts OFF. A deployed API
with PUBLIC_MODE_SUPPORTED=true consults an operator-managed DynamoDB control record on each
anonymous inspection request. Missing, disabled, expired, invalid, or unavailable settings
never grant anonymous access. An explicitly supplied invalid token is rejected.

## Four controls

1. Public-mode toggle: allow token-free use of the normal inspection webpage while enabled.
2. Upload limit: 500 MB means 500,000,000 bytes (decimal); smaller limits can be chosen.
   The API checks declared size, signs S3 PUT Content-Length, and checks actual object size
   before accepting an upload. The authenticated operator retains the existing upload limit.
3. Expiry: set a window of up to 168 hours, normally 24 hours. The API compares the saved UTC
   deadline with its clock on every public request; no restart or scheduled task is needed.
4. Quota: a durable, atomic DynamoDB transaction reserves one slot when a public inspection
   is CREATED, alongside creation of its metadata. This bounds uploads as well as processing.
   Abandoned, cancelled, and failed inspections consume a slot; slots are not refunded.
   Changing the quota preserves usage. Disabling and re-enabling before the deadline preserves
   the same window and usage. Enabling after expiry starts a new window with zero usage.

The quota is a count of admitted inspections, not a monetary budget. It does not impose a
video-duration limit or change worker retry policy. Each public inspection can start the
normal primary analysis and each normal follow-up operation only once. Response-loss retries
reuse the stored response. A failed/in-flight operation requires operator recovery rather
than starting another public job. Forced detection, custom agent arguments, and manual crop
operations require the operator token. Cached results, status polling, playback, cancellation,
and checklist changes remain available while the window is active, even when the quota is full.

## Access boundaries

Only inspections created in the current public window are accessible without the token.
Existing operator inspections and prior-window inspections remain protected, including when
their IDs are known. There are no separate visitor accounts: someone who knows another
inspection ID from the SAME current public window can access or change that inspection's
checklist. This is the agreed temporary judging mode, not private multi-user tenancy.

Expiry/disabling blocks further public API access. It does not cancel already queued jobs,
remove data, erase copies, or revoke already issued S3 URLs immediately. Public URLs generated
through these routes use the smaller of the existing 15-minute lifetime and the time remaining
in the judging window. Keep the demonstration report open: no inspection history or permanent
sharing page is added. Operator requests continue working when the quota is full or public
settings cannot be read. Operator-only controls use AWS credentials through the local AWS CLI;
there is no public admin API or change to your operator token/secret.

## Operator commands

Run from the repository root with Python 3 and your authenticated local AWS CLI.
These Python commands also run directly in Windows PowerShell and require no
PowerShell execution-policy changes. They do not request or print your API token.

```powershell
# Read settings; no changes.
python -B scripts/public_mode_control.py --status

# Example judging window: run only at the agreed start time.
python -B scripts/public_mode_control.py --enabled --hours 24 --max-video-mb 500 --max-inspections 10

# Raise the total quota while preserving admitted usage.
python -B scripts/public_mode_control.py --max-inspections 20

# Close public access immediately.
python -B scripts/public_mode_control.py --disabled
```

The optional Get-PublicMode.ps1 and Set-PublicMode.ps1 wrappers remain available
where local policy permits scripts. Windows blocked these wrappers during rehearsal,
so the Python commands above were used successfully instead. Optional Python
--profile, --region, --table, and --endpoint select existing AWS access and deployment.

Enabling before the current deadline preserves that window and usage; enabling after
expiry creates a fresh window with zero admissions. Public access defaults to OFF.
The final rehearsal window admitted three records: the initial failed start, the
successful video inspection, and one cancelled empty upload-boundary test. A later
authenticated operator inspection did not use the public quota.

## Validation

Local tests cover default-closed authentication; operator access; disabled/expired/malformed
settings; quota exhaustion and stale competing admission snapshots; atomic creation; quota
changes without counter reset; protecting earlier inspections; declared and actual upload
size boundaries; S3 Content-Length signature binding; URL lifetime; blocked custom operations;
durable once-only execution; cached retries; failure recovery; and real DynamoDB control
expressions in a Moto mock. Existing API, checklist, timestamp-control, workflow, atomic
completion/startup, and cancellation regressions are exercised. No live AWS resource was
changed by these local tests. The source snapshot omitted the historical scripts directory
and requirements.lock.txt, so a full repository test run is not claimed.

The Python regression selections pass 109 tests (87 backend/API and 22 frontend cancellation). The existing 19 bounding-box renderer
cases, 6 public upload UI cases, and JavaScript syntax check pass. Ten installer/deployment
safeguard cases pass with simulated systemd/health checks, including automatic rollback. PowerShell 7.4.6
helper checks exercise argument forwarding, decimal locale handling, switch conflict rejection,
and native failure handling with a mocked Python runner. A live Windows/AWS control test is
still needed. Browser-level Playwright tests were not run because that dependency is absent;
actual browser and end-to-end public rehearsal remain pending. Test-only requirements are separate from the frozen application/worker lockfile.

## Live deployment and verification - 2026-10-11

API release: /opt/rentready/releases/step59-public-49d6be1dc049323d.
Staging command b90b1c15-8b7a-4bbc-bd3d-5888589fa06d succeeded.
Activation command bb195e75-4483-4a49-9ae1-6c583ae2d5d5 succeeded with health,
served frontend, and initial anonymous denial verified. Deployment only changed the
API release; normal inspection processing uses the existing COOL worker lifecycle.

The local Windows project passed 54 selected Python tests, six public-upload UI checks,
and the existing 19 bounding-box renderer cases. One TestClient deprecation warning
was nonblocking. The earlier preparation checks above were performed separately.

Live checks passed:

- Token-free upload, normal processing, report, and checklist in a separate browser session.
- The timestamp control opened the uploaded four-second walkthrough.
- The checklist changed to Resolved, and a fresh anonymous GET confirmed one resolved item.
- Exhausted quota returned HTTP 429; the rejected request left admissions unchanged.
- Changing quota preserved the existing usage counter.
- Upload authorization rejected missing size (400) and 500,000,001 bytes (413),
  and accepted exactly 500,000,000 bytes (200). No 500 MB file was uploaded.
- The empty boundary-test inspection was CANCELLED without a processing job.
  Its cancellation endpoint correctly returns HTTP 202.
- Disabling blocked anonymous report reads (401). Reopening before expiry restored
  current-window access and preserved three used slots.
- A previously saved operator inspection remained unavailable anonymously (404).
- An explicitly invalid supplied token was rejected (401).
- A 36-second window expired automatically while its enabled setting remained true;
  anonymous access then returned 401. The operator subsequently set enabled=false.
- With public access OFF, the operator token authorized a new video inspection,
  follow-up analysis, and report access, as shown in the supplied UI screenshots.

The public rehearsal inspection was 5e30a92f-27e4-483a-a1bc-1c5b3e0854b3:
99/100, one Review recommended finding. Its checklist change was a demonstration
of persistence, not evidence that the physical fixture was repaired.

## Required API-role permission

The first public processing attempt stopped after upload because the instance role
lacked dynamodb:ConditionCheckItem. IAM simulation returned implicitDeny.
The operator added the inline policy RentReadyStep59PublicConditionCheck, limited
to that one action on the existing RentReady table; simulation then returned allowed,
and the subsequent public workflow succeeded. Existing policies were preserved.

The exact non-secret policy template is tracked in
scripts/step59-public-mode-condition-check-policy.json. Apply it to the actual API
runtime role before enabling this feature on another deployment; adjust its table ARN
for another account or environment. DynamoDB transaction ConditionCheck operations
require this permission in addition to the underlying read/write actions:
https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis-iam.html

If infrastructure automation manages that role, incorporate this permission there
so a later infrastructure apply preserves it. This source snapshot did not include
the infrastructure definitions; no unreviewed infrastructure file was modified.

## Demonstration footage and playback

Authorized footage: defect_13_vanity_mounting_damage.mp4, confirmed by Vincent.
Fresh analyses of this same clip have returned different finding descriptions,
priorities, and scores. Use actual saved output in the demonstration and do not
promise an identical result on every rerun. This feature did not alter the detector.

On Vincent's machine, Firefox played both the local original MP4 and the report
video with a washed-out appearance. The same local MP4 displayed correctly in Edge.
The report viewer serves the uploaded original and has no brightness filter.
Use Edge for recording and check its report viewer before recording. The precise
Firefox decoding/display cause was not diagnosed; no brightness adjustment or
transcoding workaround was added to RentReady.

## Judging handoff

Technical access and the full inspection workflow have been rehearsed. Public access
is currently OFF. Before judging, choose the required access dates and quota, enable
that window with the commands above, and provide the HTTPS site plus concise upload
instructions. The final judging window was not chosen or enabled during rehearsal.
Judges use their own authorized footage or the authorized demo clip made available
through the chosen submission materials; do not share the privileged operator token.
Keep a report tab open because this version has no inspection history or permanent
sharing page. Complete the separate demo-video/submission deliverables and publish
this Step 59 extension in Git.

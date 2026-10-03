# Step 39 — Use S3 properly

**Status: REPOSITORY PASS / LIVE AWS APPLICATION AND VERIFICATION PENDING**

Implemented October 2, 2026 against the supplied `v38b.zip`. This changes storage
organization and retention. The frozen Step 34D detector sources and settings
remain unchanged. No AWS resources were changed while preparing this ZIP.

## New inspection layout

All new inspection objects live in the existing media bucket under
`rentready/inspections/{inspection_id}/`.

| Object | Relative key |
| --- | --- |
| Original MP4 | `original/walkthrough.mp4` |
| Original MOV | `original/walkthrough.mov` |
| Selected frames | `frames/scene-001-frame-01.jpg`, `frames/scene-001-frame-02.jpg` |
| Issue evidence snapshots | `evidence/{issue_id}/frame-01.jpg`, `frame-02.jpg` |
| Agent interval/other-angle evidence | `evidence/{issue_id}/{job_id}/interval/...`, `other-angle/...` |
| Agent crop | `crops/{issue_id}/{job_id}/crop/crop_1024.jpg` |
| Policy crop | `crops/{issue_id}/{job_id}/policy/crop/crop_1024.jpg` |
| Enhanced inspection view | `evidence/{issue_id}/{job_id}/enhance/enhanced_inspection_view.jpg` |
| Processing manifest | `reports/manifest.json` |
| Final detector report | `reports/report.json` |
| Agent traces and action log | `reports/agentic/{job_id}/*.json` |
| Optional benchmark output | `reports/benchmark/cool/{run_id}/processing_report.json` |

Scene numbers in filenames start at 001. API frame indices and timestamps are
unchanged. Issue IDs are the detector/consolidator's stable IDs; they need not
be sequential numbers. Job IDs retain distinct tool runs. Before an issue report
is written, supporting full frames are copied into its evidence folder and
referenced through `preserved_evidence`, including the original source key and
timestamp. No crop is fabricated when the agent has not requested one. Clean
inspections may have no issue evidence or crops.

Existing inspections keep their `inspections/{inspection_id}/...` keys, including
the old issue-report and agent-trace paths. Reads use the keys recorded in
DynamoDB and the manifests; there is no bulk move or rewrite of existing
inspection records. Reuploading an existing legacy inspection also keeps its
namespace. The new IAM policy permits both namespaces. Evaluation datasets,
runtime evidence, and immutable worker deployment artifacts retain their
existing prefixes.

## Retention policy

| Setting in `.env` | Default | Scope |
| --- | ---: | --- |
| `S3_VIDEO_RETENTION_DAYS` | 30 | Current objects tagged `rentready-artifact=original-video` within either inspection namespace |
| `S3_NONCURRENT_VIDEO_RETENTION_DAYS` | 30 | Tagged original video versions, measured from when each version becomes noncurrent |
| `S3_ABORT_MULTIPART_DAYS` | 7 | Incomplete multipart uploads within either inspection namespace |

Frames, crops, evidence, manifests, and reports have **no automatic data expiry**
in the Step 39 rules. Separate prefix-only rules clean expired delete markers.
Videos are tagged in the signed upload request and checked/tagged again at
upload completion, using the returned VersionId when present. Existing unrelated
object tags are preserved. Evidence snapshots receive an evidence tag instead
of inheriting original-video tags.

The old rule named `expire-prototype-video` actually expired **all** objects in
`inspections/` after 30 days. The Python configuration path disables that rule,
preserves other existing lifecycle rules, and refuses to apply when another
unknown expiration rule overlaps inspection storage. Terraform replaces the
old rule when it already owns the bucket's lifecycle configuration.

S3 lifecycle acts on object age, not the date a retention tag is added. Adding
tags to an old original video can make it eligible immediately. For a versioned
bucket, current-object expiry creates a delete marker; permanent data deletion
also requires noncurrent-version expiry. With these defaults, a video that
becomes noncurrent at day 30 may remain stored for another 30 days. Deletion is
asynchronous. S3 Object Lock/legal holds, if present, can prevent version
deletion. No storage-class transitions are introduced.

After a video has expired, the video URL endpoint returns HTTP 410 with a clear
message. Retained frames and reports remain readable. Reprocessing or agent
tools that need the original video require an available original or a reupload.

## Apply to your existing AWS bucket

Use your normal AWS profile and the project folder containing `.env`. If your
environment uses a virtual environment, activate it first. Keep `.env` private.

1. Extract the updated project into your local repository, preserving your
   `.env` and `.venv`. Update the API/local user's existing IAM policy using
   `scripts/rentready_vision_iam_policy.json`. It adds the new inspection prefix,
   lifecycle reads, video-version listing, and object tagging permissions. The
   Terraform worker policy adds the new prefix and permission to tag evidence
   copies. Lifecycle administration stays outside the worker role.

2. Add the three retention settings above to `.env` if you want explicit values.
   Thirty days is the prototype default, not a tenancy recordkeeping deadline.
   Set your intended duration before applying the rules.

3. Preview the lifecycle update. This is read-only:

   ```powershell
   python scripts/configure_s3_lifecycle.py --bucket rentready-vision-dev-081087819788
   ```

   Check that `overlapping_expiration_rules` is empty and the proposed current
   video expiration filters include both the prefix and `original-video` tag.
   Unrelated rules should still appear in `configuration`. Do not paste the
   standalone example JSON directly into S3's put-lifecycle command: that API
   replaces the complete bucket configuration.

4. Apply the reviewed configuration:

   ```powershell
   python scripts/configure_s3_lifecycle.py --bucket rentready-vision-dev-081087819788 --apply
   ```

   The script first saves the previous configuration under
   `local-artifacts/s3-lifecycle/`, writes the merged rules, then reads them back.
   Local backups are excluded from Git. The normal `scripts/setup_aws.py` launcher
   also merges these scoped rules safely and backs up changes; it does not tag
   historical objects.

5. Historical originals are untagged until explicitly included. Preview them:

   ```powershell
   python scripts/configure_s3_lifecycle.py --bucket rentready-vision-dev-081087819788 --tag-existing-videos
   ```

   To include that list in retention, add `--apply`:

   ```powershell
   python scripts/configure_s3_lifecycle.py --bucket rentready-vision-dev-081087819788 --tag-existing-videos --apply
   ```

   This enumerates every page and both current/noncurrent versions, accepts only
   `original/walkthrough.mp4` or `.mov` inside the two inspection namespaces, and
   saves prior tags before each mutation. It excludes evaluation datasets,
   frames, reports, and other objects. Review the list first, particularly any
   original videos still needed for benchmark reruns. Do not tag those originals
   until you intend them to expire. Objects already deleted by the old rule are
   not restored by this update.

6. Deploy the updated API and worker. Follow the existing Step 38 immutable
   artifact build/publish procedure using the new committed source revision,
   update its version and SHA-256 in Terraform, and plan the IAM/deployment
   changes. `manage_data_resources=false` remains appropriate for your existing
   bucket; use the Python merge command above for its lifecycle. Do not enable
   Terraform bucket creation to configure a bucket that already exists.

   For a bucket already managed by this Terraform state, lifecycle rules live
   in `infra/terraform/s3_lifecycle.tf`. Keep its retention variables aligned
   with `.env`, inspect `terraform plan`, and preserve any additional lifecycle
   rules in Terraform before applying. Use one owner for the full rule set.

7. Restart the application, create a **new inspection**, upload a walkthrough,
   process it, and run issue detection. A visible-issue clip also demonstrates
   evidence snapshots; an agent crop action demonstrates `crops/`.

8. Read back the live lifecycle and inspection artifacts:

   ```powershell
   python scripts/verify_step39_s3.py --live --inspection-id YOUR_NEW_INSPECTION_ID
   ```

   This checks the six deployed rules, video tag, scene-named frame objects,
   manifest/report paths, and any preserved issue evidence. A clean report can
   pass with zero issues; run a defect inspection to exercise issue snapshots.
   `--live` alone verifies lifecycle configuration only. The verifier does not
   wait 30 days or prove that a scheduled deletion has occurred. Mark Step 39
   complete on AWS only after the new-inspection check returns `passed=true`.

## Local validation

```powershell
python scripts/verify_step39_s3.py
python scripts/verify_step34d_freeze.py
python -m pytest -q
```

The supplied ZIP contains repository verification and test results under
`evaluation/step39/`. The full suite passed with **261 tests**, including 18
new Step 39 tests. Tests used dummy AWS credentials and an explicit
`GIT_COMMIT=step39-local-test` identity because the uploaded ZIP contains no Git
history. These are local tests, not COOL/Graviton4 or live AWS measurements.
Terraform files were parsed as HCL; provider-backed `terraform validate/plan`
must run in your configured Terraform environment. The existing Starlette/httpx
deprecation warning remains unrelated to storage.

## AWS references

- [Lifecycle filters and configuration examples](https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-configuration-examples.html)
- [Current and noncurrent object expiration](https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-expire-general-considerations.html)
- [PutBucketLifecycleConfiguration replaces the complete configuration](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutBucketLifecycleConfiguration.html)

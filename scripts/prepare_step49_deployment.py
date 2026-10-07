"""Prepare checksum-pinned Step 49 packages and SSM requests without AWS writes."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_cool_worker_artifact import build_artifact


def request(instance_id, script):
    return {"DocumentName": "AWS-RunShellScript", "InstanceIds": [instance_id],
        "Comment": "Step 49: deploy guarded on-demand worker lifecycle",
        "Parameters": {"commands": [script], "executionTimeout": ["900"]}}


def prepare(*, root, output, commit, bucket, region, worker_id, api_id, function_name):
    for value in (bucket, region, worker_id, api_id, function_name):
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
            raise ValueError("Use literal AWS resource names without shell syntax")
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Use the exact committed source SHA")
    output.mkdir(parents=True, exist_ok=True)
    worker = build_artifact(root=root, output_dir=output, version="step49-" + commit[:12], source_commit=commit)
    worker_key = "deployments/cool-worker/" + worker["artifact_version"] + "/" + Path(worker["artifact"]).name
    api_zip = output / "api.zip"
    paths = []
    for directory in ("app", "scripts", "web"):
        paths += [p for p in (root / directory).rglob("*") if p.is_file()
                  and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}]
    paths += [root / name for name in ("requirements.txt", "requirements.lock.txt")]
    with zipfile.ZipFile(api_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            info = zipfile.ZipInfo(path.relative_to(root).as_posix())
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    api_sha = hashlib.sha256(api_zip.read_bytes()).hexdigest()
    api_file = output / ("api-" + api_sha + ".zip")
    api_zip.replace(api_file)
    api_key = "deployments/api/step49/" + commit + "/" + api_file.name
    tfvars = {**{"worker_artifact_s3_bucket": bucket, "worker_artifact_s3_key": worker_key,
        "worker_artifact_sha256": worker["artifact_sha256"], "worker_artifact_version": worker["artifact_version"]},
        "worker_lifecycle_enabled": True, "worker_idle_shutdown_enabled": False,
        "worker_idle_timeout_seconds": 600, "step49_api_artifact_s3_key": api_key}
    (output / "step49.auto.tfvars.json").write_text(json.dumps(tfvars, indent=2) + "\n", encoding="utf-8")

    # The API's existing role reads this exact artifact; Terraform grants no
    # wildcard deployment prefix. Existing auth/env values are preserved.
    api_script = textwrap.dedent(f'''\
        #!/bin/bash
        set -Eeuo pipefail
        package=/tmp/rentready-step49-api.zip
        release=/opt/rentready/releases/{api_sha}
        /opt/rentready/venv/bin/python - <<'PY'
        import boto3
        boto3.client('s3', region_name={region!r}).download_file({bucket!r}, {api_key!r}, '/tmp/rentready-step49-api.zip')
        PY
        printf '%s  %s\\n' '{api_sha}' "$package" | sha256sum -c -
        install -d -m 0755 "$release"
        /opt/rentready/venv/bin/python - "$package" "$release" <<'PY'
        import sys,zipfile
        from pathlib import PurePosixPath
        with zipfile.ZipFile(sys.argv[1]) as z:
            for name in z.namelist():
                p=PurePosixPath(name)
                if p.is_absolute() or '..' in p.parts: raise RuntimeError('Unsafe archive path')
            z.extractall(sys.argv[2])
        PY
        chown -R rentready:rentready "$release"
        unit=/etc/systemd/system/rentready-vision-api.service
        env=/etc/rentready/api.env
        grep -Eq '^ExecStart=/opt/rentready/venv/bin/python -m uvicorn app.main:app' "$unit"
        backup=$(mktemp -d /var/lib/rentready/step49-backup-XXXXXX)
        chmod 0700 "$backup"
        cp -p "$unit" "$backup/api.service"
        cp -p "$env" "$backup/api.env"
        rollback() {{
          cp -p "$backup/api.service" "$unit"
          cp -p "$backup/api.env" "$env"
          systemctl daemon-reload
          systemctl restart rentready-vision-api.service
        }}
        trap rollback ERR
        /opt/rentready/venv/bin/python - "$unit" "$env" "$release" <<'PY'
        import os,re,subprocess,sys
        from pathlib import Path
        unit,env,release=map(Path,sys.argv[1:])
        values={{'WORKER_LIFECYCLE_ENABLED':'true','COOL_WORKER_INSTANCE_ID':{worker_id!r},
          'WORKER_LIFECYCLE_FUNCTION_NAME':{function_name!r},'GIT_COMMIT':{commit!r}}}
        lines=[l for l in env.read_text().splitlines() if l.partition('=')[0] not in values]
        env.write_text('\\n'.join(lines+[k+'='+v for k,v in values.items()])+'\\n')
        settings=dict(os.environ)
        for line in env.read_text().splitlines():
            if line and not line.startswith('#') and '=' in line:
                k,v=line.split('=',1); settings[k]=v.strip('"\\\'')
        subprocess.run(['/opt/rentready/venv/bin/python','-c','import app.main; from app.worker_lifecycle_config import get_lifecycle_settings; assert get_lifecycle_settings().worker_lifecycle_enabled'],cwd=release,env=settings,check=True)
        service=unit.read_text()
        service,count=re.subn(r'(?m)^WorkingDirectory=.*$', 'WorkingDirectory='+str(release), service)
        if count!=1: raise RuntimeError('Expected one WorkingDirectory')
        unit.write_text(service)
        PY
        systemctl daemon-reload
        systemctl restart rentready-vision-api.service
        ready=false
        for attempt in $(seq 1 30); do
          if curl -fsS --max-time 3 -H 'Host: rentreadyvision.com' http://127.0.0.1:8000/health >/dev/null; then ready=true; break; fi
          sleep 2
        done
        test "$ready" = true
        systemctl is-active --quiet rentready-vision-api.service
        trap - ERR
        echo 'STEP49_API_DEPLOYED'
    ''')
    worker_script = textwrap.dedent(f'''\
        #!/bin/bash
        set -Eeuo pipefail
        # Check durable work before interrupting the existing worker service.
        set -a
        source /etc/environment
        set +a
        /opt/cool/venvs/python_3.12/bin/python - <<'PY'
        import boto3,os
        from pathlib import Path
        import sys
        sys.path.insert(0, '/opt/rentready-vision/current')
        # Read-only check works even on the previous worker release.
        session=boto3.Session(region_name={region!r})
        queue=session.client('sqs').get_queue_attributes(QueueUrl=os.environ['PROCESSING_QUEUE_URL'], AttributeNames=['ApproximateNumberOfMessages','ApproximateNumberOfMessagesNotVisible','ApproximateNumberOfMessagesDelayed'])['Attributes']
        if any(int(v)>0 for v in queue.values()): raise RuntimeError('Wait for queued jobs before deploying')
        table=session.resource('dynamodb').Table(os.environ['DDB_TABLE'])
        args={{'ConsistentRead':True}}
        while True:
            result=table.scan(**args)
            if any((i.get('entity_type')=='processing_job' and i.get('status') in {{'PENDING_ENQUEUE','QUEUED','RETRY_PENDING','PROCESSING'}}) or i.get('busy') is True for i in result.get('Items',[])):
                raise RuntimeError('Wait for active jobs before deploying')
            if not result.get('LastEvaluatedKey'): break
            args['ExclusiveStartKey']=result['LastEvaluatedKey']
        PY
        package=/tmp/rentready-step49-worker.tar.gz
        release=/opt/rentready-vision/releases/{worker['artifact_version']}
        aws s3 cp 's3://{bucket}/{worker_key}' "$package" --region '{region}' --only-show-errors
        printf '%s  %s\\n' '{worker['artifact_sha256']}' "$package" | sha256sum -c -
        install -d -o ubuntu -g ubuntu "$release"
        tar -xzf "$package" -C "$release" --no-same-owner
        test -f "$release/deployment-manifest.json"
        previous=$(readlink -f /opt/rentready-vision/current)
        backup=$(mktemp -d /var/lib/rentready-vision/step49-backup-XXXXXX)
        cp -p /etc/environment "$backup/environment"
        cp -p /etc/systemd/system/rentready-cool-worker.service "$backup/worker.service"
        rollback() {{
          cp -p "$backup/environment" /etc/environment
          cp -p "$backup/worker.service" /etc/systemd/system/rentready-cool-worker.service
          ln -sfn "$previous" /opt/rentready-vision/current
          systemctl daemon-reload
          systemctl restart rentready-cool-worker.service
        }}
        trap rollback ERR
        systemctl stop rentready-cool-worker.service
        /opt/cool/venvs/python_3.12/bin/python - <<'PY'
        from pathlib import Path
        p=Path('/etc/environment')
        values={{'WORKER_LIFECYCLE_ENABLED':'true','COOL_WORKER_INSTANCE_ID':{worker_id!r},'GIT_COMMIT':{commit!r},
            'WORKER_ARTIFACT_VERSION':{worker['artifact_version']!r},'WORKER_ARTIFACT_S3_URI':{'s3://'+bucket+'/'+worker_key!r},
            'WORKER_ARTIFACT_SHA256':{worker['artifact_sha256']!r},'DEPLOYMENT_MANIFEST_PATH':'/opt/rentready-vision/current/deployment-manifest.json'}}
        lines=[l for l in p.read_text().splitlines() if l.partition('=')[0] not in values]
        p.write_text('\\n'.join(lines+[k+'='+v for k,v in values.items()])+'\\n')
        PY
        chown -R ubuntu:ubuntu "$release"
        ln -sfn "$release" /opt/rentready-vision/current
        bash "$release/scripts/install_cool_worker.sh"
        systemctl is-active --quiet rentready-cool-worker.service
        trap - ERR
        echo 'STEP49_WORKER_DEPLOYED'
    ''')
    for name, data in (("api-command.json", request(api_id, api_script)), ("worker-command.json", request(worker_id, worker_script))):
        (output / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    manifest = {"step":49,"source_commit":commit,"worker":worker,
        "api":{"artifact":str(api_file),"sha256":api_sha,"s3_key":api_key},"worker_s3_key":worker_key,
        "region":region,"bucket":bucket,"idle_timeout_seconds":600}
    (output / "deployment.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist/step49")
    parser.add_argument("--bucket", default="rentready-vision-dev-081087819788")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--worker-id", default="i-0ecc68f9db17b668d")
    parser.add_argument("--api-id", default="i-0b86234abb75509b7")
    parser.add_argument("--function-name", default="rentready-vision-dev-worker-lifecycle")
    args = parser.parse_args()
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--", "app", "scripts", "web", "infra", "requirements*"], cwd=ROOT, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    prepare(root=ROOT, output=args.output_dir, commit=commit, bucket=args.bucket, region=args.region,
        worker_id=args.worker_id, api_id=args.api_id, function_name=args.function_name)


if __name__ == "__main__":
    main()

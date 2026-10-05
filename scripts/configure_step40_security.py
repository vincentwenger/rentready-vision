"""Apply Step 40 bucket controls only when --apply is supplied."""
import argparse
import sys
from pathlib import Path
import boto3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import Settings
from app.s3_security import apply_bucket_security


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--profile")
    args = parser.parse_args()
    settings = Settings(_env_file=ROOT / ".env")
    client = boto3.Session(profile_name=args.profile, region_name=settings.aws_region).client("s3")
    apply_bucket_security(client, settings.s3_bucket, backup_dir=ROOT / "local-artifacts" / "s3-security")
    print("Step 40 public-access block, ownership, and merged bucket policy applied. Run live verification next.")


if __name__ == "__main__":
    main()

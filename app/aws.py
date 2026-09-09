import boto3
from botocore.config import Config
from .config import get_settings

settings = get_settings()
session = boto3.session.Session(region_name=settings.aws_region)

s3 = session.client(
    "s3",
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"},
    ),
)

dynamodb = session.resource("dynamodb")
table = dynamodb.Table(settings.ddb_table)
sqs = session.client("sqs")
bedrock_runtime = session.client(
    "bedrock-runtime",
    config=Config(
        connect_timeout=30,
        read_timeout=3600,
        retries={"max_attempts": 2, "mode": "standard"},
    ),
)

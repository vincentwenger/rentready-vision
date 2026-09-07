from botocore.exceptions import ClientError
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import get_settings
from .routers.inspections import router as inspections_router

settings = get_settings()

app = FastAPI(
    title="RentReady Vision API",
    version="0.3.0",
    description="RentReady Vision production path: S3 upload plus durable SQS execution on a Graviton4 OpenCV COOL worker.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(inspections_router)


@app.exception_handler(ClientError)
async def aws_error_handler(_request: Request, exc: ClientError) -> JSONResponse:
    """Turn opaque AWS failures into a useful local-development response."""
    error = exc.response.get("Error", {})
    code = error.get("Code", "AWSClientError")
    if code == "ResourceNotFoundException":
        detail = (
            "The configured AWS resource was not found. Run "
            "Start_RentReady_Vision.bat again so the AWS setup step can create "
            "or verify the DynamoDB table and S3 bucket."
        )
    elif code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
        detail = (
            "AWS denied access. Verify the credentials returned by "
            "'aws sts get-caller-identity' and grant access to the configured "
            "DynamoDB table and S3 bucket."
        )
    else:
        detail = error.get("Message", "AWS request failed")
    return JSONResponse(status_code=503, content={"detail": detail, "aws_error_code": code})


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "rentready-vision-api"}


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    # The prototype has no icon yet; avoid a distracting 404 in the console.
    return Response(status_code=204)


@app.get("/")
def demo_page():
    return FileResponse("web/index.html")

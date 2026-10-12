from botocore.exceptions import ClientError
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pathlib import Path
from pydantic import ValidationError

from .config import get_settings
from .security_config import get_security_settings
from .security import SecurityMiddleware, load_api_token, content_security_policy

try:
    settings = get_settings()
    security_settings = get_security_settings()
except ValidationError:
    # The frozen base settings may include extra .env values in error inputs.
    # Never echo those values from an API startup failure.
    raise RuntimeError("Application configuration invalid; verify settings before startup") from None
operator_token = load_api_token(security_settings)
from .routers.inspections import router as inspections_router
from .routers.tv import router as tv_router
demo_file = Path(__file__).resolve().parents[1] / "web" / "index.html"

app = FastAPI(
    title="RentReady Vision API",
    version="0.6.0",
    docs_url=None if security_settings.cloud_mode else "/docs",
    redoc_url=None if security_settings.cloud_mode else "/redoc",
    openapi_url=None if security_settings.cloud_mode else "/openapi.json",
    description="RentReady Vision: durable Graviton4 OpenCV COOL evidence processing, structured findings, and explicit evidence-preserving agent tools for temporal inspection, cropping, and enhancement.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware,
                   allowed_hosts=[host.strip() for host in security_settings.allowed_hosts.split(",") if host.strip()])
# Outermost: TLS and response headers also cover CORS preflight / host errors.
app.add_middleware(SecurityMiddleware, settings=security_settings, token=operator_token,
                   csp=content_security_policy(demo_file))

app.include_router(inspections_router)
app.include_router(tv_router)


@app.exception_handler(ClientError)
async def aws_error_handler(_request: Request, exc: ClientError) -> JSONResponse:
    """Turn opaque AWS failures into a useful local-development response."""
    error = exc.response.get("Error", {})
    code = error.get("Code", "AWSClientError")
    if security_settings.cloud_mode:
        return JSONResponse(status_code=503, content={"detail": "Cloud operation unavailable; contact the operator"})
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
    return FileResponse(demo_file)


@app.get("/public-mode", include_in_schema=False)
def public_mode_status() -> dict:
    from .public_mode import control, status_document
    document = status_document(control() if security_settings.public_mode_supported else {})
    return {**document, "supported": security_settings.public_mode_supported}

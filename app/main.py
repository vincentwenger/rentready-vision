from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import get_settings
from .routers.inspections import router as inspections_router

settings = get_settings()

app = FastAPI(
    title="RentReady Vision API",
    version="0.1.0",
    description="Days 1-3 prototype: S3 upload, DynamoDB inspection state, OpenCV keyframe extraction.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(inspections_router)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "rentready-vision-api"}


@app.get("/")
def demo_page():
    return FileResponse("web/index.html")

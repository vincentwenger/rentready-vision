"""Public access is limited to records admitted in the current judging window."""
import re
from fastapi import HTTPException
from .public_mode import active, control

READ_PATH = re.compile(r"(?:|/status|/frames|/frames/urls|/frames/[0-9]+/url|/video/url|/issues|/agent|/agent/actions|/agent/views|/agent/other-angle/views)")
POST_PATHS = {"/upload", "/upload-url", "/upload-complete", "/process", "/cancel", "/agent/cancel",
              "/issues/detect", "/agent/run", "/agent/enhance", "/agent/other-angle", "/agent/policy"}


def authorize_public(request):
    value = control()
    if not active(value):
        raise HTTPException(401, "Valid operator access token required; public access is disabled or expired")
    if request.url.query:
        raise HTTPException(403, "Custom query options require operator access")
    path = request.url.path
    if path == "/inspections" and request.method == "POST":
        return value
    match = re.fullmatch(r"/inspections/([0-9a-fA-F-]{36})(.*)", path)
    if not match:
        raise HTTPException(403, "This operation requires operator access")
    inspection_id, suffix = match.groups()
    allowed = ((request.method == "GET" and READ_PATH.fullmatch(suffix))
               or (request.method == "POST" and suffix in POST_PATHS)
               or (request.method == "PATCH" and re.fullmatch(r"/checklist/items/[^/]+", suffix)))
    if not allowed:
        raise HTTPException(403, "This operation requires operator access")
    from .db import get_inspection
    item = get_inspection(inspection_id)
    if not item or item.get("public_window_id") != value["window_id"]:
        raise HTTPException(404, "Inspection not available in this public window")
    return value

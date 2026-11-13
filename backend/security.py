"""Loopback-only access, origin checks and an HttpOnly local session."""
import secrets
from urllib.parse import urlsplit
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}
ALLOWED_ORIGINS = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (8000, 5173)}
SESSION = secrets.token_urlsafe(32)
COOKIE = "omnistudy_session"


class LocalAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        host = request.url.hostname
        origin = request.headers.get("origin")
        if host not in ALLOWED_HOSTS or (origin and origin not in ALLOWED_ORIGINS and origin != f"{request.url.scheme}://{request.url.netloc}"):
            return JSONResponse({"detail": "OmniStudy accepts local app access only."}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-site access is blocked."}, status_code=403)
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path == "/api/session":
            response = JSONResponse({"ready": True})
            response.set_cookie(COOKIE, SESSION, httponly=True, samesite="strict", max_age=86400)
            response.headers["Cache-Control"] = "no-store"
            return response
        if request.url.path.startswith('/storage/'):
            from pathlib import PurePosixPath
            path = PurePosixPath(request.url.path)
            if any(part.startswith('.') for part in path.parts) or path.suffix.lower() not in ('.pdf','.pptx','.md','.txt','.png','.jpg','.jpeg','.webp'):
                return JSONResponse({'detail':'Not found'}, status_code=404)
        protected = request.url.path.startswith(("/api/", "/storage/"))
        if protected and request.url.path != "/api/health" and not secrets.compare_digest(request.cookies.get(COOKIE, ""), SESSION):
            return JSONResponse({"detail": "Open the local app to establish a session."}, status_code=401)
        response = await call_next(request)
        if protected:
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

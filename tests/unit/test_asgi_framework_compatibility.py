"""Regression coverage for the coordinated FastAPI/Starlette security upgrade."""

from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient


def _release_tuple(raw_version: str) -> tuple[int, ...]:
    """Compare stable package release numbers without a new runtime dependency."""
    return tuple(int(part) for part in raw_version.split("+", maxsplit=1)[0].split("."))


def test_patched_starlette_preserves_fastapi_lifespan_and_cors_contract():
    """The resolved ASGI stack must be patched and keep Amber's core edge behavior."""
    lifecycle: list[str] = []

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        lifecycle.append("startup")
        yield
        lifecycle.append("shutdown")

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://amber.example"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": "https://amber.example"})

    assert response.json() == {"status": "healthy"}
    assert response.headers["access-control-allow-origin"] == "https://amber.example"
    assert lifecycle == ["startup", "shutdown"]
    assert _release_tuple(version("starlette")) >= (1, 3, 1)


def test_patched_asgi_stack_preserves_multipart_and_sse_streaming_contract():
    """Upload parsing and SSE framing remain available to Amber routes after the upgrade."""
    app = FastAPI()

    @app.post("/upload")
    async def upload(file: UploadFile) -> dict[str, str]:
        return {"filename": file.filename, "content": (await file.read()).decode()}

    @app.get("/events")
    async def events() -> StreamingResponse:
        return StreamingResponse(iter(["event: ready\ndata: ok\n\n"]), media_type="text/event-stream")

    with TestClient(app) as client:
        upload_response = client.post(
            "/upload",
            files={"file": ("amber.txt", b"amber", "text/plain")},
        )
        stream_response = client.get("/events")

    assert upload_response.json() == {"filename": "amber.txt", "content": "amber"}
    assert stream_response.headers["content-type"].startswith("text/event-stream")
    assert stream_response.text == "event: ready\ndata: ok\n\n"

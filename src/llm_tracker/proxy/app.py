"""FastAPI application: catch-all proxy route."""

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from .forwarder import forward_request

app = FastAPI(title="llm-tracker proxy", docs_url=None, redoc_url=None)


@app.api_route("/{path:path}", methods=["DELETE", "GET", "PATCH", "POST", "PUT"])
async def proxy(request: Request, path: str) -> StreamingResponse:
    return await forward_request(request, path)

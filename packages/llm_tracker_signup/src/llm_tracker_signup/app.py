"""FastAPI application factory for the participant signup app.

Routes:

* ``GET /healthz`` — Fly health-check target.
* ``GET /`` — serves the public registration form.
* ``POST /register`` — accepts the form (name, email, institution),
  issues a token, redirects to ``/success?token=…``.
* ``GET /success`` — renders the token + the three install steps
  for ``claude-manage``.

No per-org auth middleware — this is a public-facing signup app and
the only authentication that matters is the per-row UNIQUE email
constraint on ``participant_registrations``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from llm_tracker_signup.config import Settings
from llm_tracker_signup.registration import (
    DuplicateEmailError,
    register_participant,
)
from llm_tracker_signup.turnstile import verify_turnstile

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
) -> FastAPI:
    resolved = settings or Settings()
    owned_engine = engine is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        eng = engine
        if eng is None:
            if not resolved.database_url:
                raise RuntimeError(
                    "LLMTRACK_DATABASE_URL is required to boot the signup app"
                )
            eng = create_async_engine(resolved.database_url)
        app.state.engine = eng
        app.state.proxy_server_url = resolved.proxy_server_url
        app.state.turnstile_site_key = resolved.turnstile_site_key
        app.state.turnstile_secret = resolved.turnstile_secret
        try:
            yield
        finally:
            if owned_engine and eng is not None:
                await eng.dispose()

    app = FastAPI(
        title="llm-tracker-signup",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    def render_form(
        request: Request,
        *,
        error: str | None = None,
        form: dict[str, str] | None = None,
        status_code: int = 200,
    ):
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "error": error,
                "form": form or {},
                "turnstile_site_key": request.app.state.turnstile_site_key,
            },
            status_code=status_code,
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def register_form(request: Request):
        return render_form(request)

    @app.post("/register")
    async def register_submit(
        request: Request,
        name: Annotated[str, Form()],
        email: Annotated[str, Form()],
        institution: Annotated[str, Form()],
        cf_turnstile_response: Annotated[
            str, Form(alias="cf-turnstile-response")
        ] = "",
    ):
        form = {"name": name, "email": email, "institution": institution}

        secret = request.app.state.turnstile_secret
        if secret:
            client_ip = request.client.host if request.client else None
            if not await verify_turnstile(secret, cf_turnstile_response, client_ip):
                return render_form(
                    request,
                    error="Captcha verification failed. Please try again.",
                    form=form,
                    status_code=400,
                )

        try:
            plaintext = await register_participant(
                request.app.state.engine,
                name=name,
                email=email,
                institution=institution,
            )
        except DuplicateEmailError:
            return render_form(
                request,
                error="This email is already registered.",
                form=form,
                status_code=400,
            )

        return RedirectResponse(
            url=f"/success?token={plaintext}",
            status_code=303,
        )

    @app.get("/success")
    async def success(request: Request, token: str):
        return templates.TemplateResponse(
            request,
            "success.html",
            {
                "token": token,
                "proxy_server_url": request.app.state.proxy_server_url,
            },
        )

    return app


app = create_app()

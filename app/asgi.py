import contextlib

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from mcp.server.transport_security import TransportSecuritySettings

from app.main import app as fastapi_app
from app.mcp_server import mcp


security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[
        "nolix-trapx-growth-api.onrender.com",
        "nolix-trapx-growth-api.onrender.com:*",
    ],
    allowed_origins=[
        "https://chatgpt.com",
        "https://chat.openai.com",
    ],
)


mcp_app = mcp.streamable_http_app(
    streamable_http_path="/",
    stateless_http=True,
    json_response=True,
    transport_security=security,
)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with mcp.session_manager.run():
        yield


app = Starlette(
    routes=[
        Mount(
            "/mcp",
            app=mcp_app,
        ),
        Mount(
            "/",
            app=fastapi_app,
        ),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=[
                "https://chatgpt.com",
                "https://chat.openai.com",
            ],
            allow_methods=[
                "GET",
                "POST",
                "DELETE",
                "OPTIONS",
            ],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Last-Event-ID",
                "Mcp-Method",
                "Mcp-Name",
                "Mcp-Protocol-Version",
                "Mcp-Session-Id",
                "X-API-Key",
            ],
            expose_headers=[
                "Mcp-Session-Id",
            ],
        )
    ],
    lifespan=lifespan,
)
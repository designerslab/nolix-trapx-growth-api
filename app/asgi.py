import contextlib

from starlette.applications import Starlette
from starlette.routing import Mount

from app.main import app as fastapi_app
from app.mcp_server import mcp


mcp_app = mcp.streamable_http_app(
    streamable_http_path="/",
    stateless_http=True,
    json_response=True,
)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with mcp.session_manager.run():
        yield


app = Starlette(
    routes=[
        Mount("/mcp", app=mcp_app),
        Mount("/", app=fastapi_app),
    ],
    lifespan=lifespan,
)
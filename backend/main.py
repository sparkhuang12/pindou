from __future__ import annotations

from contextlib import asynccontextmanager
import os

import uvicorn
from fastapi import FastAPI

from . import __version__
from .api import admin, auth, jobs, projects, system
from .middleware import register_middleware
from .state import store


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.initialize()
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="豆格 Pindou API",
        description="Backend API for image cutout, coloring and pin-bead pattern jobs.",
        version=__version__,
        lifespan=lifespan,
    )
    register_middleware(application)
    application.include_router(system.router)
    application.include_router(auth.router)
    application.include_router(projects.router)
    application.include_router(jobs.router)
    application.include_router(admin.router)
    return application


app = create_app()


def main() -> None:
    uvicorn.run(
        "backend.main:app",
        host=os.environ.get("PINDOU_HOST", "127.0.0.1"),
        port=int(os.environ.get("PINDOU_PORT", "8000")),
    )


if __name__ == "__main__":
    main()

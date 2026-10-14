"""Run the local workspace."""

from __future__ import annotations

import logging

import uvicorn

from cleaning_workspace.api.app import create_app
from cleaning_workspace.config import Settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    logging.getLogger("cleaning_workspace").info("starting %s", settings.masked())
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()

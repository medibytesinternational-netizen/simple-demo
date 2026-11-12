"""python -m medibytes.api  - serve the API and the built UI on MEDIBYTES_HOST:MEDIBYTES_PORT."""
import uvicorn

from ..config import Settings
from .app import create_app

settings = Settings.from_env()
uvicorn.run(create_app(settings), host=settings.host, port=settings.port)

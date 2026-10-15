"""ASGI entrypoint for Vercel's FastAPI runtime.

Schema migrations are an operator action before deploying this application.
No state is stored on the function's ephemeral filesystem.
"""

from app.main import create_app

app = create_app()

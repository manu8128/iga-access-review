from config.tracing import init_tracing
init_tracing()   # must be before any langchain import

from fastapi import FastAPI
from api.routes import router

app = FastAPI(
    title="IGA Access Review API",
    description="Autonomous access certification system",
    version="0.1.0",
)
app.include_router(router)

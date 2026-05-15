"""
config/tracing.py
-----------------
LangSmith tracing initialisation.
Must be imported before any LangChain/LangGraph imports.

Usage:
    from config.tracing import init_tracing
    init_tracing()   # call once at app startup
"""
import os

from config.settings import settings


def init_tracing() -> None:
    """Set LangSmith env vars before LangChain initialises.

    LangChain reads LANGCHAIN_TRACING_V2 at import time.
    Calling this before any langchain import activates tracing.
    """
    if settings.langchain_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
    else:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"

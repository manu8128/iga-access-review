from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from config.settings import settings

def get_llm(temperature: float = 0.0):
    """Return the configured LLM. Switch provider via LLM_PROVIDER env var."""
    if settings.llm_provider == "anthropic":
        return ChatAnthropic(
            model=settings.llm_model,
            anthropic_api_key=settings.anthropic_api_key,
            temperature=temperature,
        )
    elif settings.llm_provider == "openai":
        return ChatOpenAI(
            model=settings.llm_model,
            openai_api_key=settings.openai_api_key,
            temperature=temperature,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
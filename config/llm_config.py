from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from config.settings import settings


# Recommended models per provider (for reference in comments)
# anthropic : claude-haiku-4-5-20251001 (cheap) / claude-sonnet-4-6 (best)
# openai    : gpt-4o-mini (cheap) / gpt-4o (best)
# google    : gemini-2.0-flash (free tier) / gemini-1.5-pro (best)
# ollama    : llama3.1:8b (recommended) / mistral:7b / llama3.2:3b


def get_llm(temperature: float = 0.0):
    """Return the configured LLM instance.

    Provider and model are controlled entirely by environment variables:
      LLM_PROVIDER = anthropic | openai | google | ollama
      LLM_MODEL    = provider-specific model name

    Switch providers by changing .env — no code changes needed.
    """
    provider = settings.llm_provider

    if provider == "anthropic":
        return ChatAnthropic(
            model=settings.llm_model,
            anthropic_api_key=settings.anthropic_api_key,
            temperature=temperature,
        )

    elif provider == "openai":
        return ChatOpenAI(
            model=settings.llm_model,
            openai_api_key=settings.openai_api_key,
            temperature=temperature,
        )

    elif provider == "google":
        return ChatGoogleGenerativeAI(
            model=settings.llm_model,
            google_api_key=settings.google_api_key,
            temperature=temperature,
        )

    elif provider == "ollama":
        return ChatOllama(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
            format="json",
        )

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: '{provider}'. "
            f"Must be one of: anthropic, openai, google, ollama"
        )

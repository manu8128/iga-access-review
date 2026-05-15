"""
scripts/verify_llm.py
---------------------
Quick sanity check that the configured LLM provider initialises
and responds. Run before starting any phase to confirm LLM is working.

Usage:
    python scripts/verify_llm.py
"""
import sys
from pathlib import Path

# Add project root to sys.path to allow imports from project root
sys.path.append(str(Path(__file__).resolve().parent.parent))

from config.llm_config import get_llm
from config.settings import settings


def main() -> None:
    print(f"Provider : {settings.llm_provider}")
    print(f"Model    : {settings.llm_model}")
    print("Initialising LLM...", end=" ")

    llm = get_llm()
    print("OK")

    print("Sending test prompt...", end=" ")
    response = llm.invoke(
        'Respond with this exact JSON and nothing else: '
        '{"status": "ok", "message": "LLM is working"}'
    )
    print("OK")
    print(f"Response : {response.content}")


if __name__ == "__main__":
    main()

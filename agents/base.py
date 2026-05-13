"""
agents/base.py
--------------
Abstract base class for all IGA campaign agents.

Subclasses must implement a single run() method that accepts a
CampaignState and returns a partial state dict with only the keys
the agent updates. LangGraph merges partials automatically.

Properties are lazy — self.llm, self.log, and self.db are only
instantiated on first access, so stub agents that never call them
work fine without API keys or a live database.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import structlog

from config.llm_config import get_llm
from db.session import SessionLocal

if TYPE_CHECKING:
    from orchestrator.state import CampaignState


class BaseAgent(ABC):
    """Abstract base for all campaign pipeline agents."""

    # ------------------------------------------------------------------ #
    # Lazy properties                                                      #
    # ------------------------------------------------------------------ #

    @property
    def llm(self):
        """Return the configured LLM instance (temperature=0 for determinism).

        Only instantiated on first access — stubs never call this, so no
        API key is required during Phase 2 testing.
        """
        if not hasattr(self, "_llm"):
            self._llm = get_llm(temperature=0.0)
        return self._llm

    @property
    def log(self) -> structlog.BoundLogger:
        """Return a structlog logger bound to the concrete subclass name."""
        if not hasattr(self, "_log"):
            self._log = structlog.get_logger(self.__class__.__name__)
        return self._log

    @property
    def db(self):
        """Return a SQLAlchemy session.

        Caller is responsible for closing. Only instantiated on first access
        so stub agents work without a live PostgreSQL connection.
        """
        if not hasattr(self, "_db"):
            self._db = SessionLocal()
        return self._db

    # ------------------------------------------------------------------ #
    # Abstract interface                                                   #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def run(self, state: "CampaignState") -> dict:
        """Execute the agent's work.

        Args:
            state: Current campaign state (read-only — never mutate in place).

        Returns:
            Partial state dict containing only the keys this agent updates.
            LangGraph will merge this into the full state.
        """
        ...

"""
WorkMind — Base Agent
Abstract base class for all WorkMind agents.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseAgent(ABC):
    name: str

    @abstractmethod
    async def run(self, query: str, context: dict) -> dict:
        """
        Process *query* given *context* and return a result dict.
        All agents must implement this method.
        """
        ...

"""What a model reads: the system text and the user message.

    Prompt(system="You are ...", user="Day: ...")

Each service keeps its wording in a prompts module that builds these; the code that calls the model only
sends them (llm.py: system=prompt.system, the first message prompt.user). Every service that calls a model
starts from one: Main's planner, memory's consolidation, the builder's coders, the gateway's decide scorer.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Prompt(BaseModel):
    model_config = ConfigDict(frozen=True)

    system: str
    user: str

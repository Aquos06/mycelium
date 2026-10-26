"""The decide step: a small scorer behind the gateway's `decide` slot picks which notes a vague question is
about, then recall hops from them (MEMORY.md §4).

catalogue.py   the candidates of round one: every note, the period summaries, the recent days and their facts, one line each
expand.py      the candidates of the next round: what the picked notes link to, what links to them, their older facts
decider.py     the loop: score, pick above the floor, hop, score again; one trace.decide per run

Recall keeps the exact rungs first (dates, periods, names, links). The loop runs only when they found nothing,
so the scorer is asked about the vague questions and nothing else.
"""

from .catalogue import candidate_text, catalogue, fact_candidate
from .decider import DecideError, Decider
from .expand import expansion

__all__ = ["DecideError", "Decider", "candidate_text", "catalogue", "expansion", "fact_candidate"]

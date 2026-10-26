"""Routing only: the body is WebGateway.chat / WebGateway.feedback (service.py)."""

from __future__ import annotations

from fastapi import APIRouter

from ..api.deps import Gateway
from .schemas import ChatIn, FeedbackIn, Sent

router = APIRouter()


@router.post("", response_model=Sent, summary="say something to Main on channel web (sense.chat)")
async def chat(req: ChatIn, gw: Gateway) -> Sent:
    return await gw.chat(req)


@router.post("/feedback", response_model=Sent, summary="answer an out.ask or vote on an out.say (sense.feedback)")
async def feedback(req: FeedbackIn, gw: Gateway) -> Sent:
    return await gw.feedback(req)

"""The three Phase 1 features, independent of HTTP so they can be scripted and tested."""

import asyncio

from pydantic import BaseModel

from . import prompts
from .config import settings
from .deck import deck_as_text
from .llm import Usage, json_call
from .masking import mask
from .schemas import (Deck, DeckSummary, NotesRequest, NotesResponse, Outline, OutlineRequest,
                      SlideContent, SlideNotes)

WORDS_PER_MINUTE = 130


def _safe(text: str) -> str:
    return mask(text) if settings.mask_pii else text


def _cap_citations(points, valid: set[int]):
    """Drop slide numbers the deck does not have, so citations can be trusted."""
    for p in points:
        p.slides = sorted({n for n in p.slides if n in valid})


async def summarise(deck: Deck, usage: Usage) -> DeckSummary:
    prompt = prompts.SUMMARY.format(deck=_safe(deck_as_text(deck)))
    result = await json_call(prompt, DeckSummary, usage, temperature=0.2)
    valid = {s.index for s in deck.slides}
    for group in (result.key_points, result.decisions, result.action_items, result.open_questions):
        _cap_citations(group, valid)
    return result


class _NotesOnly(BaseModel):
    notes: str


async def speaker_notes(req: NotesRequest, usage: Usage) -> NotesResponse:
    slides = req.deck.slides
    wanted = set(req.slides) if req.slides else {s.index for s in slides}
    words = max(20, round(req.seconds_per_slide * WORDS_PER_MINUTE / 60))

    async def one(pos: int, s: SlideContent) -> SlideNotes:
        if s.notes and not req.overwrite_existing:
            return SlideNotes(index=s.index, notes=s.notes, skipped=True)
        prev_title = slides[pos - 1].title if pos > 0 else "(none, this is the first slide)"
        next_title = slides[pos + 1].title if pos + 1 < len(slides) else "(none, this is the last slide)"
        transition = ("End with a one-sentence bridge to the next slide."
                      if pos + 1 < len(slides) else "End by closing the presentation.")
        single = Deck(slide_count=1, slides=[s])
        prompt = prompts.NOTES.format(
            index=s.index, total=len(slides), audience=req.audience, tone=req.tone, words=words,
            seconds=req.seconds_per_slide, transition=transition,
            prev_title=_safe(prev_title), next_title=_safe(next_title),
            slide=_safe(deck_as_text(single)))
        out = await json_call(prompt, _NotesOnly, usage, temperature=0.5)
        return SlideNotes(index=s.index, notes=out.notes.strip())

    tasks = [one(pos, s) for pos, s in enumerate(slides) if s.index in wanted]
    return NotesResponse(notes=list(await asyncio.gather(*tasks)))


async def outline(req: OutlineRequest, usage: Usage) -> Outline:
    if req.source_text.strip():
        grounding = prompts.GROUNDED
        source = f"\n<untrusted_source>\n{_safe(req.source_text)}\n</untrusted_source>"
    else:
        grounding, source = prompts.UNGROUNDED, ""
    prompt = prompts.OUTLINE.format(prompt=_safe(req.prompt), audience=req.audience,
                                    count=req.slide_count, grounding=grounding, source=source)
    return await json_call(prompt, Outline, usage, temperature=0.4)

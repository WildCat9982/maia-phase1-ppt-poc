"""Request and response models. The LLM's JSON output is validated against these."""

from typing import Literal

from pydantic import BaseModel, Field


# ---- Deck extraction -------------------------------------------------------

class SlideContent(BaseModel):
    index: int  # 1-based, as users see it
    layout: str
    title: str = ""
    body: list[str] = []
    tables: list[list[list[str]]] = []
    notes: str = ""
    has_images: bool = False


class Deck(BaseModel):
    slide_count: int
    slides: list[SlideContent]


# ---- 1.1 Summarisation -----------------------------------------------------

class CitedPoint(BaseModel):
    text: str
    slides: list[int] = Field(default_factory=list, description="Slide numbers that support the point")


class DeckSummary(BaseModel):
    executive_summary: str
    key_points: list[CitedPoint]
    decisions: list[CitedPoint] = []
    action_items: list[CitedPoint] = []
    open_questions: list[CitedPoint] = []


# ---- 1.3 Speaker notes -----------------------------------------------------

class NotesRequest(BaseModel):
    deck: Deck
    seconds_per_slide: int = Field(60, ge=10, le=600)
    audience: str = "senior management"
    tone: Literal["Professional", "Friendly", "Collaborative"] = "Professional"
    slides: list[int] | None = None  # None = all slides
    overwrite_existing: bool = False


class SlideNotes(BaseModel):
    index: int
    notes: str
    skipped: bool = False  # True when the slide already had notes and overwrite was off


class NotesResponse(BaseModel):
    notes: list[SlideNotes]


# ---- 1.2 Prompt to presentation --------------------------------------------

class OutlineRequest(BaseModel):
    prompt: str = Field(..., min_length=3)
    source_text: str = ""  # optional email or document text to ground the deck
    slide_count: int = Field(8, ge=3, le=20)
    audience: str = "senior management"


class OutlineSlide(BaseModel):
    layout: Literal["title", "section", "bullets"]
    title: str
    bullets: list[str] = []
    notes: str = ""


class Outline(BaseModel):
    title: str
    subtitle: str = ""
    slides: list[OutlineSlide]


class QualityReport(BaseModel):
    slides: int
    bullets_over_limit: list[int]  # slide numbers with more than 5 bullets
    long_bullets: list[int]  # slide numbers with a bullet over 12 words
    empty_slides: list[int]

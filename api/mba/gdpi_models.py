"""Pydantic models for GDPI (WAT / GD / PI) preparation — contract: docs/mba-api.md "GDPI".

Content (``mbaGdpiItems``) is ProCounsel-original guidance written in ``data/mba/gdpi/{wat,gd,pi}.json``
and imported by ``scripts/mba/import_gdpi.py``. ``GdpiItemRecord`` is both the import validator
and the stored document shape.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

GdpiKind = Literal["wat", "gd", "pi"]
TopicGroup = Literal["business", "economy", "technology", "society", "abstract"]
PiGroup = Literal["personal", "academics", "work", "current_affairs", "hobbies", "situational", "stress"]
Background = Literal["engineering", "commerce", "arts", "science"]
ContentStatus = Literal["draft", "published", "archived"]

TOPIC_GROUPS: tuple[str, ...] = ("business", "economy", "technology", "society", "abstract")
PI_GROUPS: tuple[str, ...] = ("personal", "academics", "work", "current_affairs", "hobbies", "situational", "stress")
BACKGROUNDS: tuple[str, ...] = ("engineering", "commerce", "arts", "science")
GROUPS_BY_KIND: dict[str, tuple[str, ...]] = {"wat": TOPIC_GROUPS, "gd": TOPIC_GROUPS, "pi": PI_GROUPS}

ID_RE = re.compile(r"^(wat|gd|pi)-[a-z0-9]+(?:-[a-z0-9]+)*$")
Text = Field(min_length=3, max_length=700)


class GdAngle(BaseModel):
    angle: str = Field(min_length=3, max_length=80)
    forView: str = Field(min_length=20, max_length=500, alias="for")
    againstView: str = Field(min_length=20, max_length=500, alias="against")

    model_config = {"populate_by_name": True}


class GdpiItemRecord(BaseModel):
    """One topic / question. ``kind`` comes from the file it lives in."""

    id: str = Field(min_length=4, max_length=80)
    kind: GdpiKind
    group: str
    prompt: str = Field(min_length=3, max_length=300)
    framing: str = Field(min_length=30, max_length=700)  # WAT/GD: framing note; PI: what the panel is assessing
    lookFor: list[str] = Field(default_factory=list, max_length=6)  # WAT/GD: what evaluators look for
    angles: list[GdAngle] = Field(default_factory=list, max_length=4)  # GD only
    structure: list[str] = Field(default_factory=list, max_length=6)  # strong answer / essay structure
    avoid: list[str] = Field(default_factory=list, max_length=5)  # common pitfalls
    background: Background | None = None  # PI academics only
    status: ContentStatus = "published"
    source: dict = Field(default_factory=lambda: {"kind": "original", "title": "ProCounsel original GDPI guidance"})

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _check(self) -> "GdpiItemRecord":
        problems: list[str] = []
        if not ID_RE.match(self.id) or not self.id.startswith(f"{self.kind}-"):
            problems.append(f"id {self.id!r} must look like '{self.kind}-<slug>'")
        if self.group not in GROUPS_BY_KIND[self.kind]:
            problems.append(f"group {self.group!r} is not one of {GROUPS_BY_KIND[self.kind]}")
        for name in ("lookFor", "structure", "avoid"):
            for entry in getattr(self, name):
                if not isinstance(entry, str) or not (3 <= len(entry.strip()) <= 400):
                    problems.append(f"{name} entries must be 3-400 characters")
                    break
        if self.kind == "wat" and not 3 <= len(self.lookFor) <= 6:
            problems.append("WAT topics need 3-6 lookFor points")
        if self.kind == "gd" and not 3 <= len(self.angles) <= 4:
            problems.append("GD topics need 3-4 angles")
        if self.kind != "gd" and self.angles:
            problems.append("only GD topics have angles")
        if self.kind == "pi":
            if not 3 <= len(self.structure) <= 6:
                problems.append("PI questions need 3-6 structure steps")
            if (self.group == "academics") != (self.background is not None):
                problems.append("background is required for academics questions and only for them")
        elif self.background is not None:
            problems.append("background is only for PI questions")
        if problems:
            raise ValueError("; ".join(problems))
        return self


# ---------------------------------------------------------------- API shapes
class GdpiAngleOut(BaseModel):
    angle: str
    forView: str
    againstView: str


class GdpiItem(BaseModel):
    id: str
    kind: GdpiKind
    group: str
    prompt: str
    framing: str
    lookFor: list[str]
    angles: list[GdpiAngleOut]
    structure: list[str]
    avoid: list[str]
    background: Background | None
    source: dict


class GdpiItemsResponse(BaseModel):
    items: list[GdpiItem]


class SessionInput(BaseModel):
    kind: Literal["pi", "wat"]
    focus: str | None = Field(default=None, max_length=40)  # PI: a PI group; WAT: a topic group
    background: Background | None = None  # PI: picks the academics question
    itemId: str | None = Field(default=None, max_length=80)  # WAT: write on this topic
    durationMinutes: Literal[15, 20] | None = None  # WAT only (default 15)

    model_config = {"extra": "forbid"}


class AnswerInput(BaseModel):
    questionId: str = Field(min_length=1, max_length=80)
    answerText: str = Field(min_length=1, max_length=3000)

    model_config = {"extra": "forbid"}


class FeedbackScores(BaseModel):
    structure: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    completeness: int = Field(ge=1, le=5)


class Feedback(BaseModel):
    scores: FeedbackScores | None  # null only when fallback is true
    strengths: list[str]
    improvements: list[str]
    betterOutline: list[str]
    fallback: bool  # true = the AI reply was unusable; outline comes from the question's guidance


class FillerCount(BaseModel):
    word: str
    count: int


class Delivery(BaseModel):
    """Voice answers only: computed from the transcript and recording length (the audio itself is not kept)."""

    durationSeconds: int
    wordsPerMinute: int
    pace: Literal["slow", "steady", "fast"]
    fillerCount: int
    fillers: list[FillerCount]
    notes: list[str]


class SessionAnswer(BaseModel):
    questionId: str
    mode: Literal["text", "voice"]
    delivery: Delivery | None  # voice answers only
    answerText: str
    wordCount: int
    overtime: bool
    feedback: Feedback
    answeredAt: str


class SessionSummaryStats(BaseModel):
    answered: int
    total: int
    averageScores: FeedbackScores | None = None  # rounded means over answers with scores
    overall: float | None = None  # mean of the four, 1 decimal


class GdpiSession(BaseModel):
    id: str
    kind: Literal["pi", "wat"]
    status: Literal["in_progress", "completed"]
    title: str
    focus: str | None
    background: Background | None
    durationMinutes: int | None
    startedAt: str
    endsAt: str | None
    serverNow: str
    completedAt: str | None
    questions: list[GdpiItem]
    answers: list[SessionAnswer]
    summary: SessionSummaryStats


class GdpiSessionSummary(BaseModel):
    id: str
    kind: Literal["pi", "wat"]
    status: Literal["in_progress", "completed"]
    title: str
    focus: str | None
    answered: int
    total: int
    overall: float | None
    startedAt: str
    completedAt: str | None


class GdpiSessionsResponse(BaseModel):
    sessions: list[GdpiSessionSummary]


class AnswerResponse(BaseModel):
    answer: SessionAnswer
    session: GdpiSession
    remainingToday: int

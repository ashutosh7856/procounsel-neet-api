"""Pydantic models mirroring docs/mba-api.md (camelCase on the wire)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

SectionId = Literal["VARC", "DILR", "QA"]
QuestionType = Literal["MCQ", "TITA"]
SourceKind = Literal["official", "licensed", "faculty", "original"]
MistakeCategory = Literal["concept", "calculation", "misread", "selection", "time_pressure", "guess"]
SECTION_IDS: tuple[str, ...] = ("VARC", "DILR", "QA")


class Source(BaseModel):
    kind: SourceKind
    title: str
    url: str | None = None
    year: int | None = None
    retrievedAt: str | None = None


# ---------------------------------------------------------------- exams / papers
class ExamSection(BaseModel):
    id: SectionId
    name: str
    questionCount: int | None = Field(default=None, ge=0)  # null = not officially announced
    durationMinutes: int = Field(gt=0)


class MarkingRule(BaseModel):
    type: QuestionType
    correct: float
    incorrect: float
    unanswered: float


class ExamVersion(BaseModel):
    year: int
    sections: list[ExamSection]
    marking: list[MarkingRule]
    totalDurationMinutes: int = Field(gt=0)
    sectionOrderLocked: bool
    source: Source


class Exam(BaseModel):
    id: Literal["cat"]
    name: str
    conductingBody: str
    officialUrl: str
    versions: list[ExamVersion]


class ExamsResponse(BaseModel):
    exams: list[Exam]


class PaperSectionSummary(BaseModel):
    id: SectionId
    questionCount: int


class PaperSummary(BaseModel):
    id: str
    title: str
    examVersionYear: int | None = None
    year: int | None = None
    slot: int | None = None
    questionCount: int
    sections: list[PaperSectionSummary]
    source: Source | None = None


class PapersResponse(BaseModel):
    papers: list[PaperSummary]


# ---------------------------------------------------------------- questions
class QuestionOption(BaseModel):
    id: str
    textHtml: str


class QuestionSet(BaseModel):
    id: str
    kind: Literal["passage", "dilr_set", "data"]
    title: str | None = None
    contentHtml: str
    images: list[str] | None = None


class QuestionPublic(BaseModel):
    id: str
    examId: Literal["cat"] = "cat"
    paperId: str | None = None
    section: SectionId
    topic: str | None = None
    subtopic: str | None = None
    type: QuestionType
    stemHtml: str
    options: list[QuestionOption] | None = None
    setId: str | None = None
    set: QuestionSet | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    year: int | None = None
    slot: int | None = None
    source: Source


class PracticeQuestion(QuestionPublic):
    bookmarked: bool = False


class QuestionsResponse(BaseModel):
    questions: list[PracticeQuestion]
    nextCursor: str | None


class PracticeAnswerInput(BaseModel):
    questionId: str = Field(min_length=1, max_length=200)
    answer: str = Field(min_length=1, max_length=50)
    timeSpentMs: int = Field(ge=0, le=6 * 60 * 60 * 1000)


class PracticeStats(BaseModel):
    attempts: int
    correct: int


class PracticeAnswerResponse(BaseModel):
    correctAnswer: str
    solutionHtml: str | None = None
    isCorrect: bool
    stats: PracticeStats


class BookmarkResponse(BaseModel):
    bookmarked: bool


class MistakeItem(BaseModel):
    question: QuestionPublic
    lastAnswer: str
    category: MistakeCategory | None = None
    note: str | None = None
    nextReviewAt: str | None = None
    retries: int


class MistakesResponse(BaseModel):
    items: list[MistakeItem]


class MistakePatch(BaseModel):
    category: MistakeCategory | None = None
    note: str | None = Field(default=None, max_length=2000)


class DailyResponse(BaseModel):
    date: str
    questions: list[QuestionPublic]
    completed: int


# ---------------------------------------------------------------- profile
class MbaProfileInput(BaseModel):
    targetExam: Literal["cat"]
    examDate: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    targetPercentile: float | None = Field(default=None, ge=0, le=100)
    currentLevel: Literal["beginner", "intermediate", "advanced"]
    weeklyStudyHours: float = Field(ge=1, le=80)
    studyDays: list[int] = Field(max_length=7)
    targetPrograms: list[str] | None = Field(default=None, max_length=50)

    @field_validator("examDate")
    @classmethod
    def _valid_date(cls, value: str | None) -> str | None:
        if value is not None:
            from datetime import date

            date.fromisoformat(value)  # raises ValueError -> 422
        return value

    @field_validator("studyDays")
    @classmethod
    def _valid_days(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("studyDays must be integers 0 (Sun) to 6 (Sat).")
        return sorted(set(value))

    @field_validator("targetPrograms")
    @classmethod
    def _valid_programs(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        if any(len(item) > 200 for item in cleaned):
            raise ValueError("targetPrograms entries must be at most 200 characters.")
        return cleaned


class MbaProfile(MbaProfileInput):
    userId: str
    createdAt: str
    updatedAt: str


# ---------------------------------------------------------------- tests / attempts
class TestSummary(BaseModel):
    id: str
    title: str
    kind: Literal["full_mock", "sectional"]
    paperId: str
    sections: list[SectionId]
    durationMinutes: int
    questionCount: int


class TestsResponse(BaseModel):
    tests: list[TestSummary]


class AttemptCreate(BaseModel):
    testId: str = Field(min_length=1, max_length=200)


class ResponseEntry(BaseModel):
    answer: str | None = None
    markedForReview: bool = False
    timeSpentMs: int = 0


class AttemptQuestion(QuestionPublic):
    sectionIndex: int


class Attempt(BaseModel):
    id: str
    testId: str
    title: str
    status: Literal["in_progress", "submitted"]
    currentSection: SectionId
    sectionOrder: list[SectionId]
    sectionEndsAt: str
    serverNow: str
    questions: list[AttemptQuestion]
    responses: dict[str, ResponseEntry]
    savedSeq: int


class ResponseInput(BaseModel):
    questionId: str = Field(min_length=1, max_length=200)
    answer: str | None = Field(default=None, max_length=50)
    markedForReview: bool = False
    timeSpentMs: int = Field(default=0, ge=0, le=6 * 60 * 60 * 1000)


class ResponsesPatch(BaseModel):
    seq: int = Field(ge=0, le=2**53 - 1)  # JS safe integer; also keeps Firestore int64 happy
    responses: list[ResponseInput] = Field(max_length=200)


class SavedSeq(BaseModel):
    savedSeq: int


class AttemptSummary(BaseModel):
    id: str
    testId: str
    title: str
    status: Literal["in_progress", "submitted"]
    startedAt: str
    submittedAt: str | None = None
    score: float | None = None
    maxScore: float | None = None


class AttemptsResponse(BaseModel):
    attempts: list[AttemptSummary]


class SectionResult(BaseModel):
    id: SectionId
    score: float
    maxScore: float
    attempted: int
    correct: int
    incorrect: int
    unanswered: int
    accuracy: float | None
    timeSpentMs: int


class ResultQuestion(QuestionPublic):
    correctAnswer: str
    solutionHtml: str | None = None
    isCorrect: bool | None = None
    yourAnswer: str | None
    timeSpentMs: int
    marks: float


class AttemptResult(BaseModel):
    id: str
    testId: str
    title: str
    submittedAt: str
    score: float
    maxScore: float
    sections: list[SectionResult]
    questions: list[ResultQuestion]


# ---------------------------------------------------------------- dashboard
class SectionProgress(BaseModel):
    id: SectionId
    attempted: int
    correct: int
    accuracy: float | None


class DashboardTotals(BaseModel):
    questionsAttempted: int
    correct: int
    bookmarked: int
    mistakesDue: int
    mocksCompleted: int


class Priority(BaseModel):
    kind: Literal["resume_mock", "review_mistakes", "practice_weak_section", "take_diagnostic", "daily_challenge"]
    title: str
    detail: str
    href: str


class Streak(BaseModel):
    current: int
    lastActiveDate: str | None


class Dashboard(BaseModel):
    profile: MbaProfile | None
    daysToExam: int | None
    sections: list[SectionProgress]
    totals: DashboardTotals
    recentAttempts: list[AttemptSummary]
    inProgressAttempt: AttemptSummary | None
    priorities: list[Priority] = Field(max_length=3)
    streak: Streak


# ---------------------------------------------------------------- AI tutor
class HintInput(BaseModel):
    questionId: str = Field(min_length=1, max_length=200)
    level: Literal[1, 2, 3]
    studentAnswer: str | None = Field(default=None, max_length=50)


class HintResponse(BaseModel):
    text: str
    level: Literal[1, 2, 3]
    remainingToday: int
    grounded: Literal[True] = True


# ---------------------------------------------------------------- admin (content review)
ContentStatus = Literal["draft", "published", "archived"]
ReviewAction = Literal["approve", "reject", "flag"]
HTML_MAX = 100_000  # keeps every doc far below Firestore's 1 MiB limit


class StatusCounts(BaseModel):
    draft: int = 0  # draft and not flagged
    flagged: int = 0  # draft and flagged by a reviewer
    published: int = 0
    archived: int = 0  # rejected (or removed by a re-import)
    missing: int = 0  # listed in the paper but no question doc


class AdminPaperSection(BaseModel):
    id: SectionId
    questionCount: int
    counts: StatusCounts


class AdminPaper(BaseModel):
    id: str
    title: str
    status: ContentStatus
    examVersionYear: int | None = None
    year: int | None = None
    slot: int | None = None
    questionCount: int
    counts: StatusCounts
    sections: list[AdminPaperSection]
    readyToPublish: bool  # every question published (and at least one)
    source: Source | None = None
    updatedAt: str | None = None
    publishedAt: str | None = None
    publishedBy: str | None = None


class AdminPapersResponse(BaseModel):
    papers: list[AdminPaper]


class AdminSet(BaseModel):
    id: str
    kind: Literal["passage", "dilr_set", "data"]
    title: str | None = None
    contentHtml: str
    images: list[str] | None = None
    version: int
    updatedAt: str | None = None


class HistoryEntry(BaseModel):
    version: int
    editedBy: str
    editedAt: str
    changes: list[str]
    summary: str


class AdminQuestion(BaseModel):
    id: str
    key: str | None = None
    paperId: str | None = None
    section: SectionId
    number: int | None = None
    type: QuestionType
    stemHtml: str
    options: list[QuestionOption] | None = None
    setId: str | None = None
    set: AdminSet | None = None
    topic: str | None = None
    subtopic: str | None = None
    difficulty: Literal["easy", "medium", "hard"] | None = None
    correctAnswer: str
    solutionHtml: str | None = None
    source: Source
    status: ContentStatus
    flagged: bool
    reviewAction: Literal["approved", "rejected", "flagged"] | None = None
    reviewNote: str | None = None
    reviewedBy: str | None = None
    reviewedAt: str | None = None
    version: int
    history: list[HistoryEntry]
    updatedAt: str | None = None


class AdminPaperQuestionsResponse(BaseModel):
    paper: AdminPaper
    questions: list[AdminQuestion]


class QuestionEdit(BaseModel):
    """Only the fields that are sent are changed; ``null`` clears an optional field."""

    model_config = {"extra": "forbid"}

    stemHtml: str | None = Field(default=None, max_length=HTML_MAX)
    options: list[QuestionOption] | None = Field(default=None, max_length=10)
    answer: str | int | float | None = None  # MCQ: an option id; TITA: the exact answer
    solutionHtml: str | None = Field(default=None, max_length=HTML_MAX)
    topic: str | None = Field(default=None, max_length=200)
    subtopic: str | None = Field(default=None, max_length=200)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    expectedVersion: int | None = Field(default=None, ge=1)  # 409 if the question changed since


class SetEdit(BaseModel):
    model_config = {"extra": "forbid"}

    contentHtml: str | None = Field(default=None, max_length=HTML_MAX)
    title: str | None = Field(default=None, max_length=300)
    expectedVersion: int | None = Field(default=None, ge=1)


class ReviewInput(BaseModel):
    model_config = {"extra": "forbid"}

    action: ReviewAction
    note: str | None = Field(default=None, max_length=2000)

"""Pydantic models mirroring docs/mba-api.md (camelCase on the wire)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

SectionId = Literal["VARC", "DILR", "QA"]  # CAT; CAT-only features (drills, planner, estimator…) keep using it
# Any exam's section id (CAT: VARC/DILR/QA; others from data/mba/exams-config/<examId>.json), validated
# against the exam's config by the importer and the test engine — not a fixed enum.
ExamSectionId = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9]{0,11}$")]
ExamId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,30}$")]
EXAM_IDS: tuple[str, ...] = ("cat", "xat", "snap", "nmat", "cmat", "mat", "gmat", "mah-mba-cet")  # profile targets
QuestionType = Literal["MCQ", "TITA"]
SourceKind = Literal["official", "licensed", "faculty", "original"]
MistakeCategory = Literal["concept", "calculation", "misread", "selection", "time_pressure", "guess"]
Confidence = Literal["sure", "unsure", "guess"]  # student's optional self-rating of an answer (practice modes)
SECTION_IDS: tuple[str, ...] = ("VARC", "DILR", "QA")


class Source(BaseModel):
    kind: SourceKind
    title: str
    url: str | None = None
    year: int | None = None
    retrievedAt: str | None = None


# ---------------------------------------------------------------- exams / papers
class ExamSection(BaseModel):
    id: ExamSectionId
    name: str
    questionCount: int | None = Field(default=None, ge=0)  # null = not officially announced
    durationMinutes: int | None = Field(default=None, gt=0)  # null = no own timer (shares a timer block)
    countsInTotal: bool = True  # False: scored and shown separately (XAT GK)


class MarkingRule(BaseModel):
    type: QuestionType
    correct: float
    incorrect: float
    unanswered: float
    sections: list[ExamSectionId] | None = None  # null = every section; else only these (XAT Part 1 vs GK)


class TimerBlock(BaseModel):
    """Sections that share one timer; the student moves freely between them while it runs.

    A version without ``timerBlocks`` times every section on its own (CAT). A block with a
    single section has that section's id.
    """

    id: ExamSectionId
    name: str | None = None
    sectionIds: list[ExamSectionId] = Field(min_length=1)
    durationMinutes: int = Field(gt=0)


class UnansweredPenalty(BaseModel):
    """XAT: ``marks`` for each unanswered question of ``sections`` beyond the first ``freeCount``."""

    sections: list[ExamSectionId]
    freeCount: int = Field(ge=0)
    marks: float


class ExamVersion(BaseModel):
    year: int
    sections: list[ExamSection]
    marking: list[MarkingRule]
    totalDurationMinutes: int = Field(gt=0)
    sectionOrderLocked: bool  # False: the student picks the order of the timer blocks (NMAT, GMAT)
    source: Source
    timerBlocks: list[TimerBlock] | None = None
    unansweredPenalty: UnansweredPenalty | None = None
    scoring: Literal["official", "practice"] = "official"  # practice = not the exam's own (scaled/adaptive) score
    scoringNote: str | None = None  # plain-language marking/timing summary for the instructions screen


class Exam(BaseModel):
    id: ExamId
    name: str
    conductingBody: str
    officialUrl: str
    versions: list[ExamVersion]
    adaptive: bool = False  # the real exam is computer-adaptive; ours is a fixed-form practice test


class ExamsResponse(BaseModel):
    exams: list[Exam]


class PaperSectionSummary(BaseModel):
    id: ExamSectionId
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
    isPyq: bool = False  # actual past CAT paper (year + slot + official source)


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
    examId: str = "cat"
    paperId: str | None = None
    section: ExamSectionId
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
    isPyq: bool = False  # from an actual past CAT paper; label it "CAT {year} Slot {slot}"


class PracticeQuestion(QuestionPublic):
    bookmarked: bool = False


class QuestionsResponse(BaseModel):
    questions: list[PracticeQuestion]
    nextCursor: str | None


class PracticeAnswerInput(BaseModel):
    questionId: str = Field(min_length=1, max_length=200)
    answer: str = Field(min_length=1, max_length=50)
    timeSpentMs: int = Field(ge=0, le=6 * 60 * 60 * 1000)
    confidence: Confidence | None = None


class PracticeStats(BaseModel):
    attempts: int
    correct: int


class PracticeAnswerResponse(BaseModel):
    correctAnswer: str
    solutionHtml: str | None = None
    alternativeApproaches: list[str] | None = None  # other ways to solve it (HTML), after the main solution
    videoUrl: str | None = None  # https video solution (YouTube etc.)
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
    # Every exam the student is preparing for (multi-select; mocks/practice filter by it). null = CAT only.
    targetExams: list[str] | None = Field(default=None, max_length=len(EXAM_IDS))

    @field_validator("targetExams")
    @classmethod
    def _valid_exams(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = [item for item in value if item not in EXAM_IDS]
        if unknown:
            raise ValueError(f"targetExams must be among {list(EXAM_IDS)}.")
        return [exam for exam in EXAM_IDS if exam in value]  # de-duplicated, stable order

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
    paperTitle: str = ""
    sections: list[ExamSectionId]
    durationMinutes: int
    questionCount: int
    isPyq: bool = False  # previous-year CAT paper vs ProCounsel original
    year: int | None = None
    slot: int | None = None
    examVersionYear: int | None = None
    examId: str = "cat"
    timerBlocks: list[TimerBlock] = []  # how the test is timed (one block per section for CAT)
    sectionOrderLocked: bool = True  # False: pick the block order when starting (AttemptCreate.sectionOrder)


class TestsResponse(BaseModel):
    tests: list[TestSummary]


class AttemptCreate(BaseModel):
    testId: str = Field(min_length=1, max_length=200)
    # Timer-block order chosen by the student; only for tests with sectionOrderLocked false (NMAT, GMAT).
    sectionOrder: list[str] | None = Field(default=None, max_length=10)


class ResponseEntry(BaseModel):
    answer: str | None = None
    markedForReview: bool = False
    timeSpentMs: int = 0
    confidence: Confidence | None = None


class AttemptQuestion(QuestionPublic):
    sectionIndex: int


class Attempt(BaseModel):
    id: str
    testId: str
    title: str
    status: Literal["in_progress", "submitted"]
    currentSection: ExamSectionId  # first section of the current timer block
    sectionOrder: list[ExamSectionId]
    sectionEndsAt: str  # end of the current timer block
    serverNow: str
    questions: list[AttemptQuestion]
    responses: dict[str, ResponseEntry]
    savedSeq: int
    examId: str = "cat"
    timerBlocks: list[TimerBlock] = []  # in attempt order; answers can change only in the current one
    currentBlock: str | None = None


class ResponseInput(BaseModel):
    questionId: str = Field(min_length=1, max_length=200)
    answer: str | None = Field(default=None, max_length=50)
    markedForReview: bool = False
    timeSpentMs: int = Field(default=0, ge=0, le=6 * 60 * 60 * 1000)
    confidence: Confidence | None = None  # stored only with an answer


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
    id: ExamSectionId
    score: float
    maxScore: float
    attempted: int
    correct: int
    incorrect: int
    unanswered: int
    accuracy: float | None
    timeSpentMs: int
    countsInTotal: bool = True  # False: shown on its own, not part of score/maxScore (XAT GK)
    penalty: float = 0  # unanswered-question penalty included in score (XAT)


class ResultQuestion(QuestionPublic):
    correctAnswer: str
    solutionHtml: str | None = None
    alternativeApproaches: list[str] | None = None
    videoUrl: str | None = None
    isCorrect: bool | None = None
    yourAnswer: str | None
    timeSpentMs: int
    marks: float
    confidence: Confidence | None = None


class ConfidenceBucket(BaseModel):
    answered: int
    correct: int
    incorrect: int


class ConfidenceBreakdown(BaseModel):
    """Answered questions of a result by the student's self-rating (``unrated`` = answered without one)."""

    sure: ConfidenceBucket
    unsure: ConfidenceBucket
    guess: ConfidenceBucket
    unrated: ConfidenceBucket


class ProcounselPercentile(BaseModel):
    """Standing among ProCounsel students' first attempts of the same test — NOT an official CAT percentile."""

    percentile: float | None  # null until at least ``minStudents`` other students have a first attempt
    students: int  # other students compared with
    minStudents: int
    score: float  # the score that was compared
    basis: Literal["first_attempt"] = "first_attempt"
    note: str


class AttemptResult(BaseModel):
    id: str
    testId: str
    title: str
    submittedAt: str
    score: float
    maxScore: float
    sections: list[SectionResult]
    questions: list[ResultQuestion]
    isPyq: bool = False
    year: int | None = None
    slot: int | None = None
    procounselPercentile: ProcounselPercentile | None = None
    confidence: ConfidenceBreakdown | None = None
    examId: str = "cat"


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
    id: ExamSectionId
    questionCount: int
    counts: StatusCounts


class HistoryEntry(BaseModel):
    version: int
    editedBy: str
    editedAt: str
    changes: list[str]
    summary: str


class AdminPaper(BaseModel):
    id: str
    title: str
    status: ContentStatus
    examId: str = "cat"  # the exam config the paper follows (GET /admin/exams)
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
    # Admin authoring (api/mba/authoring.py): edit version/history and optional schedule window.
    version: int = 1
    history: list[HistoryEntry] = []
    availableFrom: str | None = None
    availableUntil: str | None = None
    schedule: Literal["always", "upcoming", "live", "ended"] = "always"


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
    key: str | None = None
    section: ExamSectionId | None = None
    status: ContentStatus = "draft"


class AdminQuestion(BaseModel):
    id: str
    key: str | None = None
    paperId: str | None = None
    section: ExamSectionId
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
    alternativeApproaches: list[str] | None = None
    videoUrl: str | None = None
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
    sets: list[AdminSet] = []  # every non-archived set of the paper (also ones no question uses yet)


class SourceInput(BaseModel):
    """Content source as authored in the Admin panel (validated with scripts/mba/paper_format.py)."""

    model_config = {"extra": "forbid"}

    kind: SourceKind
    title: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=1000)
    year: int | None = None
    retrievedAt: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=1000)


class QuestionEdit(BaseModel):
    """Only the fields that are sent are changed; ``null`` clears an optional field."""

    model_config = {"extra": "forbid"}

    stemHtml: str | None = Field(default=None, max_length=HTML_MAX)
    options: list[QuestionOption] | None = Field(default=None, max_length=10)
    answer: str | int | float | None = None  # MCQ: an option id; TITA: the exact answer
    solutionHtml: str | None = Field(default=None, max_length=HTML_MAX)
    alternativeApproaches: list[str] | None = Field(default=None, max_length=5)  # null or [] clears
    videoUrl: str | None = Field(default=None, max_length=500)  # https only; null clears
    topic: str | None = Field(default=None, max_length=200)
    subtopic: str | None = Field(default=None, max_length=200)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    type: QuestionType | None = None  # switching MCQ <-> TITA: send options (or null) and answer too
    setId: str | None = None          # a set of the same paper and section, or null for none
    source: SourceInput | None = None
    expectedVersion: int | None = Field(default=None, ge=1)  # 409 if the question changed since


class SetEdit(BaseModel):
    model_config = {"extra": "forbid"}

    contentHtml: str | None = Field(default=None, max_length=HTML_MAX)
    title: str | None = Field(default=None, max_length=300)
    kind: Literal["passage", "dilr_set", "data"] | None = None
    images: list[str] | None = Field(default=None, max_length=20)  # http(s) image URLs; null clears
    expectedVersion: int | None = Field(default=None, ge=1)


class ReviewInput(BaseModel):
    model_config = {"extra": "forbid"}

    action: ReviewAction
    note: str | None = Field(default=None, max_length=2000)

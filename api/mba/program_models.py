"""Phase D models: MBA programmes, official CAT minimum thresholds, eligibility, shortlist.

Contract: docs/mba-api.md ("Phase D"). File format: docs/mba-content-format.md.
``InstituteRecord`` is both the data-file schema (data/mba/programs/*.json) and the
stored shape of an ``mbaPrograms/{slug}`` document.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Category = Literal["General", "EWS", "NC-OBC", "SC", "ST"]
CATEGORIES: tuple[str, ...] = ("General", "EWS", "NC-OBC", "SC", "ST")
Gender = Literal["Male", "Female", "Transgender"]
CutoffStage = Literal["shortlisting"]
EligibilityStatus = Literal["meets_minimum", "below_minimum", "unknown"]
FailedOn = Literal["overall", "VARC", "DILR", "QA"]
ShortlistStatus = Literal["interested", "shortlisted", "applied", "interview", "offer", "declined"]

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
BATCH_RE = re.compile(r"^\d{4}-\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

Percentile = Field(default=None, ge=0, le=100)


class OfficialSource(BaseModel):
    """Every figure in Phase D data is official: an IIM document/website or nirfindia.org."""

    model_config = ConfigDict(extra="ignore")

    kind: Literal["official"]
    title: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://")
    year: int | None = None
    retrievedAt: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    quote: str | None = None  # verbatim evidence; kept in the data file / DB, not returned by the API


class ProgramRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1)
    durationYears: float | None = Field(default=None, gt=0, le=5)
    feeTotal: int | None = Field(default=None, gt=0)
    feeNote: str | None = None
    feeSource: OfficialSource | None = None
    intake: int | None = Field(default=None, gt=0)
    intakeNote: str | None = None
    intakeSource: OfficialSource | None = None
    medianSalary: int | None = Field(default=None, gt=0)
    medianSalaryYear: int | None = None
    salaryNote: str | None = None
    salarySource: OfficialSource | None = None

    @model_validator(mode="after")
    def _figures_need_sources(self) -> "ProgramRecord":
        if self.feeTotal is not None and self.feeSource is None:
            raise ValueError(f"{self.code}: feeTotal needs feeSource")
        if self.intake is not None and self.intakeSource is None:
            raise ValueError(f"{self.code}: intake needs intakeSource")
        if self.medianSalary is not None and (self.salarySource is None or self.medianSalaryYear is None):
            raise ValueError(f"{self.code}: medianSalary needs salarySource and medianSalaryYear")
        return self


class CutoffRecord(BaseModel):
    """Published MINIMUM CAT percentiles for shortlisting (not closing percentiles)."""

    model_config = ConfigDict(extra="ignore")

    policyBatch: str = Field(pattern=BATCH_RE.pattern)
    stage: CutoffStage = "shortlisting"
    programCode: str | None = None  # None = the institute's first (flagship) programme
    category: Category
    pwd: bool = False
    gender: Gender | None = None  # None = applies to every gender (most IIMs)
    overall: float | None = Percentile
    varc: float | None = Percentile
    dilr: float | None = Percentile
    qa: float | None = Percentile
    notes: str | None = None
    source: OfficialSource

    @model_validator(mode="after")
    def _some_threshold(self) -> "CutoffRecord":
        if all(v is None for v in (self.overall, self.varc, self.dilr, self.qa)):
            raise ValueError("cutoff record without any threshold")
        return self


class InstituteRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slug: str = Field(pattern=SLUG_RE.pattern)
    name: str = Field(min_length=1)
    shortName: str = Field(min_length=1)
    city: str | None = None
    state: str | None = None
    website: str | None = None
    programs: list[ProgramRecord] = Field(default_factory=list)
    cutoffs: list[CutoffRecord] = Field(default_factory=list)
    cutoffNotes: str | None = None  # e.g. non-CAT minimums or "policy not published"

    @model_validator(mode="after")
    def _consistent(self) -> "InstituteRecord":
        codes = [p.code for p in self.programs]
        if len(codes) != len(set(codes)):
            raise ValueError("duplicate programme codes")
        seen = set()
        for c in self.cutoffs:
            if c.programCode is not None and c.programCode not in codes:
                raise ValueError(f"cutoff programCode {c.programCode!r} is not a programme of {self.slug}")
            key = (c.policyBatch, c.stage, c.programCode or (codes[0] if codes else None), c.category, c.pwd, c.gender)
            if key in seen:
                raise ValueError(f"duplicate cutoff record {key}")
            seen.add(key)
        return self


# ---------------------------------------------------------------- API shapes
class SourceOut(BaseModel):
    kind: Literal["official"]
    title: str
    url: str
    year: int | None = None
    retrievedAt: str


class DataFreshness(BaseModel):
    retrievedAt: str | None  # latest retrieval date of any source used
    cutoffPolicyBatches: list[str]  # admission-policy batches the thresholds come from
    note: str


class ProgramKeyFacts(BaseModel):
    code: str
    name: str
    durationYears: float | None = None
    feeTotal: int | None = None
    intake: int | None = None
    medianSalary: int | None = None
    medianSalaryYear: int | None = None


class ProgramDetail(ProgramKeyFacts):
    feeNote: str | None = None
    feeSource: SourceOut | None = None
    intakeNote: str | None = None
    intakeSource: SourceOut | None = None
    salaryNote: str | None = None
    salarySource: SourceOut | None = None


class CutoffOut(BaseModel):
    policyBatch: str
    stage: CutoffStage
    programCode: str | None
    category: Category
    pwd: bool
    gender: Gender | None
    overall: float | None
    varc: float | None
    dilr: float | None
    qa: float | None
    notes: str | None
    source: SourceOut


class InstituteSummary(BaseModel):
    slug: str
    name: str
    shortName: str
    city: str | None
    state: str | None
    website: str | None
    programs: list[ProgramKeyFacts]
    hasCutoffs: bool
    dataFreshness: DataFreshness


class InstituteDetail(InstituteSummary):
    programs: list[ProgramDetail]  # type: ignore[assignment]
    cutoffs: list[CutoffOut]
    cutoffNotes: str | None
    sources: list[SourceOut]  # every distinct source used on this page


class ProgramsResponse(BaseModel):
    institutes: list[InstituteSummary]
    dataFreshness: DataFreshness


class EligibilityInput(BaseModel):
    category: Category
    pwd: bool = False
    gender: Gender | None = None  # needed only where an IIM publishes gender-specific minimums
    overall: float = Field(ge=0, le=100)
    varc: float | None = Percentile
    dilr: float | None = Percentile
    qa: float | None = Percentile


class Thresholds(BaseModel):
    overall: float | None
    varc: float | None
    dilr: float | None
    qa: float | None


class EligibilityResult(BaseModel):
    slug: str
    name: str
    shortName: str
    programCode: str | None
    programName: str | None
    policyBatch: str | None
    status: EligibilityStatus
    failedOn: list[FailedOn]
    notChecked: list[FailedOn]  # thresholds that exist but the student gave no percentile for
    thresholds: Thresholds | None
    notes: str | None
    source: SourceOut | None


class EligibilityResponse(BaseModel):
    input: EligibilityInput
    results: list[EligibilityResult]
    counts: dict[str, int]
    methodology: str
    limitations: str
    dataFreshness: DataFreshness


class ShortlistInput(BaseModel):
    status: ShortlistStatus = "interested"
    deadline: str | None = None  # YYYY-MM-DD
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("deadline")
    @classmethod
    def _date(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        from datetime import date

        if not DATE_RE.match(value):
            raise ValueError("deadline must be YYYY-MM-DD")
        date.fromisoformat(value)
        return value


class ShortlistItem(BaseModel):
    slug: str
    name: str | None  # None if the institute is no longer listed
    shortName: str | None
    status: ShortlistStatus
    deadline: str | None
    notes: str | None
    createdAt: str
    updatedAt: str


class ShortlistResponse(BaseModel):
    items: list[ShortlistItem]


class ShortlistDeleteResponse(BaseModel):
    removed: bool

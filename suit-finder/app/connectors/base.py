"""Base types shared across the entire pipeline.

Design: evidence-centric. PageSignals carries raw text signals;
EvidenceBlock wraps a text fragment with its provenance.
All parsers consume EvidenceBlock lists, never raw HTML.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Page-level raw signals
# ---------------------------------------------------------------------------

class PageSignals(BaseModel):
    """Raw text signals extracted from a rendered page.

    Selectors are used ONLY to locate these text buckets.
    Size, material, etc. are NOT extracted via selectors.
    """

    url: str
    title_text: str = ""
    price_text: str = ""
    status_text: str = ""
    description_text: str = ""
    all_text: str = ""
    specs_text: str = ""      # テーブル形式の仕様欄
    brand_text: str = ""
    category_text: str = ""
    image_urls: list[str] = Field(default_factory=list)
    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class EvidenceBlock(BaseModel):
    """A unit of evidence: a text fragment with its origin.

    source: where the text came from (title / price / status /
            description / specs / all_text / brand / category)
    block_type: semantic type hint for parsers
    confidence: prior confidence of the text being accurate (0–1)
    metadata: arbitrary key-value for traceability
    """

    source: str
    text: str
    block_type: str = "text"
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidencePackage(BaseModel):
    """Full evidence package for one listing."""

    item_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    url: str
    source_site: str = "yahoo_auctions"
    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    page_signals: PageSignals
    evidence_blocks: list[EvidenceBlock] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser I/O
# ---------------------------------------------------------------------------

class ParserInput(BaseModel):
    """Input to any parser."""

    item_id: str
    evidence_blocks: list[EvidenceBlock]
    page_signals: PageSignals


class MeasurementValue(BaseModel):
    """A single measured value with provenance."""

    value: float
    unit: str = "cm"
    confidence: float
    evidence: str          # The text fragment that yielded this value
    source: str            # EvidenceBlock.source


class CategoricalValue(BaseModel):
    """A single categorical value with provenance."""

    value: str
    confidence: float
    evidence: str
    source: str


# ---------------------------------------------------------------------------
# Parser outputs
# ---------------------------------------------------------------------------

class JacketMeasurements(BaseModel):
    shoulder_cm: Optional[MeasurementValue] = None
    chest_width_cm: Optional[MeasurementValue] = None
    length_cm: Optional[MeasurementValue] = None
    sleeve_cm: Optional[MeasurementValue] = None


class PantsMeasurements(BaseModel):
    waist_flat_cm: Optional[MeasurementValue] = None
    waist_circumference_cm: Optional[MeasurementValue] = None
    rise_cm: Optional[MeasurementValue] = None
    inseam_cm: Optional[MeasurementValue] = None
    hem_width_cm: Optional[MeasurementValue] = None
    thigh_cm: Optional[MeasurementValue] = None
    total_length_cm: Optional[MeasurementValue] = None
    hem_finish: Optional[CategoricalValue] = None  # "double" | "single"


class SizeParserOutput(BaseModel):
    jacket: JacketMeasurements = Field(default_factory=JacketMeasurements)
    pants: PantsMeasurements = Field(default_factory=PantsMeasurements)
    unknown_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class PriceParserOutput(BaseModel):
    listing_type: Optional[str] = None       # "auction" | "fixed_price" | "buy_now_only"
    current_price_jpy: Optional[int] = None
    buy_now_price_jpy: Optional[int] = None
    shipping_price_jpy: Optional[int] = None
    shipping_included: Optional[bool] = None
    evidence: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class StatusParserOutput(BaseModel):
    normalized_status: Optional[str] = None  # "active" | "sold" | "ended" | "unknown"
    raw_status: str = ""
    evidence: str = ""
    confidence: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class MaterialParserOutput(BaseModel):
    """Fiber content for outer and lining fabrics.

    Each entry in outer_fibers / lining_fibers:
        {"fiber": str, "percentage": int | None}
    """

    outer_fibers: list[dict[str, Any]] = Field(default_factory=list)
    lining_fibers: list[dict[str, Any]] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class StyleParserOutput(BaseModel):
    """Jacket style features: breasted type, button count/color."""

    button_type: Optional[str] = None   # "single" | "double"
    button_count: Optional[int] = None
    button_color: Optional[str] = None  # "gold" | "silver" | "black" | ...
    unknown_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class ConditionParserOutput(BaseModel):
    """Item condition: grade, stain, hole."""

    grade: Optional[str] = None         # "S" | "A" | "B" | "C" | "D"
    has_stain: Optional[bool] = None
    has_hole: Optional[bool] = None
    unknown_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class MergedStructuredAttributes(BaseModel):
    """All parser outputs merged into one structure."""

    item_id: str
    size: SizeParserOutput
    price: PriceParserOutput
    status: StatusParserOutput
    material: MaterialParserOutput
    style: StyleParserOutput
    condition: ConditionParserOutput


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

class DecisionOutput(BaseModel):
    """Final judgement for one listing."""

    item_id: str
    verdict: str                         # "MATCH" | "REVIEW" | "NO_MATCH"
    score: float                         # 0–1 composite score
    reasons: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    needs_llm_review: bool = False
    needs_human_review: bool = False
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Connector protocol
# ---------------------------------------------------------------------------

class BaseConnector:
    """Abstract connector – each site subclasses this."""

    site: str = "unknown"

    async def fetch_page_signals(self, url: str) -> PageSignals:
        raise NotImplementedError

    async def search(self, query: str, **kwargs: Any) -> list[str]:
        """Return list of item URLs."""
        raise NotImplementedError

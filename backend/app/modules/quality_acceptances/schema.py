"""质量验收接口的请求与响应模型。"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QualityAcceptanceCreate(BaseModel):
    """创建质量验收记录时提交的字段。"""

    delivery_id: int = Field(gt=0)
    inspector_id: int = Field(gt=0)


class QualityAssignmentDelivery(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    delivery_no: str


class QualityInspectorOption(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str


class QualityAssignmentOptions(BaseModel):
    deliveries: list[QualityAssignmentDelivery]
    inspectors: list[QualityInspectorOption]


class QualityAcceptanceResult(BaseModel):
    """提交质量检测结果时的字段。"""

    result: str = Field(pattern="^(PASSED|PARTIAL|FAILED|REINSPECTION)$")
    test_result: dict[str, Any] | list[Any] | None = None
    item_results: list["QualityItemResult"] | None = None
    certificate_complete: bool = False
    report_file_id: int | None = Field(default=None, gt=0)
    conclusion: str | None = Field(default=None, max_length=2000)


class QualityItemResult(BaseModel):
    delivery_item_id: int = Field(gt=0)
    tests: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_tests(self):
        if any(not name.strip() or not value.strip() for name, value in self.tests.items()):
            raise ValueError("检测项目和值不能为空")
        return self


class QualityAcceptanceRead(BaseModel):
    """质量验收响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    acceptance_no: str
    delivery_id: int
    inspector_id: int
    result: str
    inspection_time: datetime | None
    test_result: dict | list | None
    certificate_complete: int
    report_file_id: int | None
    conclusion: str | None
    created_at: datetime
    updated_at: datetime


class QualityAcceptancePage(BaseModel):
    """质量验收分页响应。"""

    items: list[QualityAcceptanceRead]
    total: int
    page: int
    page_size: int


class QualityReportFile(BaseModel):
    id: int
    file_name: str
    uploaded_at: datetime


class QualityReportReviewRequest(BaseModel):
    file_id: int = Field(gt=0)
    delivery_item_id: int | None = Field(default=None, gt=0)
    standard_id: int | None = Field(default=None, gt=0)


class QualityReviewTarget(BaseModel):
    delivery_item_id: int
    product_id: int
    product_name: str
    product_model: str | None = None
    batch_no: str | None
    line_no: int


class QualityCriterion(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    aliases: list[str] = Field(default_factory=list, max_length=10)
    kind: str = Field(pattern="^(NUMERIC|TEXT)$")
    unit: str | None = Field(default=None, max_length=30)
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    expected_text: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_condition(self):
        """按数值或文本项目类型校验必填条件，并拒绝相互冲突的限值。"""
        if self.kind == "NUMERIC":
            if not self.unit or (self.minimum is None and self.maximum is None) or self.expected_text is not None:
                raise ValueError("数值项目需要单位和至少一个限值，且不能设置文本条件")
            if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
                raise ValueError("数值项目下限不能大于上限")
        elif not self.expected_text or self.unit or self.minimum is not None or self.maximum is not None:
            raise ValueError("文本项目需要预期文本，且不能设置数值条件")
        return self


class QualityStandardCreate(BaseModel):
    source_reference: str = Field(min_length=1, max_length=255)
    criteria: list[QualityCriterion] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_names(self):
        """确保同一版本中检测项目名称及别名均非空且不重复。"""
        names = [alias.strip().casefold() for item in self.criteria for alias in [item.name, *item.aliases]]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValueError("检测项目名称和别名不能为空或重复")
        return self


class QualityStandardRead(QualityStandardCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    version_no: int
    created_by: int
    created_at: datetime


class QualityReportCheck(BaseModel):
    item_name: str
    report_value: str | None = None
    recorded_value: str | None = None
    source_quote: str | None = None
    source_location: str | None = None
    status: str
    standard_criterion: str | None = None
    standard_requirement: str | None = None
    standard_status: str = "NOT_CONFIGURED"


class QualityReportReview(BaseModel):
    review_id: int | None = None
    acceptance_id: int
    delivery_item_id: int | None = None
    product_name: str | None = None
    product_model: str | None = None
    report_product_name: str | None = None
    report_product_model: str | None = None
    product_status: str = "UNVERIFIED"
    standard_id: int | None = None
    standard_version: int | None = None
    standard_source: str | None = None
    file_id: int
    file_name: str
    report_batch_no: str | None = None
    expected_batch_nos: list[str]
    batch_status: str
    checks: list[QualityReportCheck]
    warnings: list[str]
    reviewed_at: datetime


class QualityReviewHistory(BaseModel):
    id: int
    file_name: str
    product_name: str
    batch_no: str | None
    standard_version: int | None
    status: str
    created_at: datetime
    reviewed_at: datetime | None
    reviewer_note: str | None


class QualityReviewDecision(BaseModel):
    status: str = Field(pattern="^(CONFIRMED|NEEDS_CORRECTION)$")
    reviewer_note: str = Field(min_length=1, max_length=2000)
    correction_items: list[str] = Field(default_factory=list)


class QualityCorrectionAction(BaseModel):
    item_name: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=2000)


class QualityCorrectionRead(BaseModel):
    id: int
    review_id: int
    item_name: str
    status: str
    note: str
    actor_id: int
    created_at: datetime


class QualityReportComparison(BaseModel):
    item_name: str
    values: list[dict[str, Any]]
    conflict: bool


class QualityReportSummary(BaseModel):
    delivery_item_id: int
    reviews: list[QualityReviewHistory]
    comparisons: list[QualityReportComparison]
    corrections: list[QualityCorrectionRead]

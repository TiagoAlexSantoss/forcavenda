from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class CatalogProductUpsert(BaseModel):
    sku: str = Field(min_length=1, max_length=60, examples=["SIM-GLIFO"])
    name: str = Field(min_length=1, max_length=180, examples=["Herbicida glifosato"])
    unit: str = Field(default="UN", max_length=20)
    product_group_code: str | None = Field(default=None, max_length=40)
    product_class_code: str | None = Field(default=None, max_length=40)
    purchase_price: Decimal = Field(default=Decimal("0"), ge=0)
    cost_price: Decimal = Field(default=Decimal("0"), ge=0)
    suggested_margin_percent: Decimal = Field(default=Decimal("0"), ge=0)
    sale_price: Decimal | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=800)
    active: bool = True


class CatalogProductBatch(BaseModel):
    items: list[CatalogProductUpsert] = Field(min_length=1, max_length=1000)


class CatalogCustomerUpsert(BaseModel):
    external_id: str = Field(min_length=1, max_length=80, examples=["CLI-001"])
    source: str = Field(default="integration", min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=180)
    customer_profile_code: str = Field(default="NOVO", max_length=40)
    document_number: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=180)
    phone: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=120)
    state_code: str | None = Field(default=None, min_length=2, max_length=2)
    active: bool = True


class CatalogCustomerBatch(BaseModel):
    items: list[CatalogCustomerUpsert] = Field(min_length=1, max_length=1000)


class CatalogPriceItemUpsert(BaseModel):
    product_sku: str = Field(min_length=1, max_length=60)
    base_price: Decimal = Field(ge=0)
    margin_percent: Decimal = Field(default=Decimal("5"), ge=0)
    active: bool = True


class CatalogPriceTableUpsert(BaseModel):
    code: str = Field(min_length=1, max_length=40, examples=["TABELA-2026"])
    name: str = Field(min_length=1, max_length=160)
    correction_mode: Literal["outside", "inside"] = "outside"
    monthly_rate: Decimal = Field(default=Decimal("0"), ge=0)
    base_date: date = Field(default_factory=date.today)
    active: bool = True
    items: list[CatalogPriceItemUpsert] = Field(default_factory=list, max_length=5000)


class CatalogPriceTableBatch(BaseModel):
    items: list[CatalogPriceTableUpsert] = Field(min_length=1, max_length=100)


class CatalogUpsertResult(BaseModel):
    key: str
    id: int
    status: Literal["created", "updated"]


class CatalogBatchResponse(BaseModel):
    received: int
    created: int
    updated: int
    results: list[CatalogUpsertResult]


class CatalogProductExport(BaseModel):
    id: int
    sku: str
    name: str
    unit: str
    product_group_code: str | None = None
    product_class_code: str | None = None
    purchase_price: Decimal
    cost_price: Decimal
    suggested_margin_percent: Decimal
    sale_price: Decimal
    description: str | None = None
    active: bool


class CatalogProductExportPage(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[CatalogProductExport]

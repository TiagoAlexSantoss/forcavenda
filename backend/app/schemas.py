from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ProductGroupBase(BaseModel):
    code: str
    name: str
    description: str | None = None
    active: bool = True


class ProductGroupCreate(ProductGroupBase):
    pass


class ProductGroupUpdate(ProductGroupBase):
    pass


class ProductGroupRead(ProductGroupBase):
    id: int

    class Config:
        from_attributes = True


class ProductClassBase(BaseModel):
    product_group_id: int | None = None
    code: str
    name: str
    description: str | None = None
    active: bool = True


class ProductClassCreate(ProductClassBase):
    pass


class ProductClassUpdate(ProductClassBase):
    pass


class ProductClassRead(ProductClassBase):
    id: int
    product_group_name: str | None = None

    class Config:
        from_attributes = True


class ProductBase(BaseModel):
    product_group_id: int | None = None
    product_class_id: int | None = None
    sku: str
    name: str
    unit: str = "UN"
    purchase_price: Decimal = Decimal("0.00")
    cost_price: Decimal = Decimal("0.00")
    sale_price: Decimal = Decimal("0.00")
    description: str | None = None
    active: bool = True


class ProductCreate(ProductBase):
    pass


class ProductUpdate(ProductBase):
    pass


class ProductRead(ProductBase):
    id: int
    product_group_name: str | None = None
    product_class_name: str | None = None

    class Config:
        from_attributes = True


class CustomerRead(BaseModel):
    id: str
    source: str
    customer_profile_id: int | None = None
    customer_profile_name: str | None = None
    credit_limit: Decimal = Decimal("0.00")
    name: str
    document_number: str | None = None
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    state_code: str | None = None
    active: bool = True


class CustomerBase(BaseModel):
    customer_profile_id: int
    name: str
    document_number: str | None = None
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    state_code: str | None = None
    active: bool = True


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(CustomerBase):
    pass


class CustomerProfileBase(BaseModel):
    code: str
    name: str
    description: str | None = None
    max_inactive_days: int = 180
    max_overdue_days: int = 0
    block_without_movement: bool = False
    block_overdue_titles: bool = True
    active: bool = True


class CustomerProfileCreate(CustomerProfileBase):
    pass


class CustomerProfileUpdate(CustomerProfileBase):
    pass


class CustomerProfileRead(CustomerProfileBase):
    id: int

    class Config:
        from_attributes = True


class CustomerProfileAssign(BaseModel):
    customer_profile_id: int


class PriceTableBase(BaseModel):
    code: str
    name: str
    correction_mode: str = "outside"
    monthly_rate: Decimal = Decimal("0.00")
    base_date: date
    active: bool = True


class PriceTableCreate(PriceTableBase):
    pass


class PriceTableUpdate(PriceTableBase):
    pass


class PriceTableRead(PriceTableBase):
    id: int

    class Config:
        from_attributes = True


class PriceTableItemBase(BaseModel):
    product_id: int
    base_price: Decimal
    margin_percent: Decimal = Decimal("5.00")
    active: bool = True


class PriceTableItemCreate(PriceTableItemBase):
    pass


class PriceTableItemUpdate(PriceTableItemBase):
    pass


class PriceTableItemRead(PriceTableItemBase):
    id: int
    price_table_id: int
    product_sku: str | None = None
    product_name: str | None = None

    class Config:
        from_attributes = True


class PricePreviewRead(BaseModel):
    price_table_id: int
    product_id: int
    base_price: Decimal
    corrected_price: Decimal
    correction_mode: str
    correction_factor: Decimal
    days: int


class SalesOrderItemCreate(BaseModel):
    product_id: int
    quantity: Decimal
    negotiated_unit_price: Decimal | None = None


class SalesOrderItemCancel(BaseModel):
    quantity: Decimal


class SalesOrderCreate(BaseModel):
    customer_id: str
    price_table_id: int
    order_date: date
    payment_due_date: date
    notes: str | None = None
    items: list[SalesOrderItemCreate] = Field(default_factory=list)


class SalesOrderUpdate(SalesOrderCreate):
    pass


class SalesOrderItemRead(BaseModel):
    id: int
    product_id: int
    product_sku: str
    product_name: str
    quantity: Decimal
    cancelled_quantity: Decimal = Decimal("0.00")
    base_unit_price: Decimal
    corrected_unit_price: Decimal
    negotiated_unit_price: Decimal = Decimal("0.00")
    price_margin_percent: Decimal = Decimal("5.00")
    min_unit_price: Decimal = Decimal("0.00")
    max_unit_price: Decimal = Decimal("0.00")
    cost_unit_price: Decimal = Decimal("0.00")
    total_amount: Decimal
    total_cost_amount: Decimal = Decimal("0.00")
    gross_profit_amount: Decimal = Decimal("0.00")
    profitability_percent: Decimal = Decimal("0.00")
    commercial_status: str = "approved"
    commercial_reason: str | None = None
    cancellation_status: str = "active"

    class Config:
        from_attributes = True


class AuthorizationReasonRead(BaseModel):
    segment: str
    scope: str
    reason: str
    status: str = "pending"
    item_id: int | None = None
    item_name: str | None = None
    suggested_role: str | None = None


class SalesOrderRead(BaseModel):
    id: int
    order_number: str
    customer_source: str
    customer_external_id: str
    customer_name: str
    price_table_id: int
    price_table_name: str | None = None
    order_date: date
    payment_due_date: date
    status: str
    approval_stage: str = "draft"
    approval_notes: str | None = None
    financial_approved_at: datetime | None = None
    commercial_approved_at: datetime | None = None
    total_amount: Decimal
    total_cost_amount: Decimal = Decimal("0.00")
    gross_profit_amount: Decimal = Decimal("0.00")
    profitability_percent: Decimal = Decimal("0.00")
    notes: str | None = None
    authorization_reasons: list[AuthorizationReasonRead] = Field(default_factory=list)
    items: list[SalesOrderItemRead] = Field(default_factory=list)

    class Config:
        from_attributes = True

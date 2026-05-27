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
    company_ids: list[int] = Field(default_factory=list)

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
    company_ids: list[int] = Field(default_factory=list)

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
    default_warehouse_id: int | None = None
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
    default_warehouse_name: str | None = None
    controls_lot: bool = False
    lot_type: str = "none"
    company_ids: list[int] = Field(default_factory=list)

    class Config:
        from_attributes = True


class ProductLotConfigUpdate(BaseModel):
    controls_lot: bool = False
    lot_type: str = Field("none", pattern="^(seeds|general|none)$")


class StockBalanceRead(BaseModel):
    warehouse_id: int
    warehouse_name: str | None = None
    balance_type_id: int
    balance_code: str
    balance_name: str
    product_source: str
    product_external_id: str
    product_sku: str
    product_name: str
    balance_quantity: Decimal


class StockMovementRead(BaseModel):
    id: int
    warehouse_id: int
    warehouse_name: str | None = None
    operation_code: str | None = None
    operation_name: str | None = None
    document_type_code: str | None = None
    document_number: str | None = None
    document_series: str | None = None
    issue_date: date | None = None
    movement_date: date | None = None
    product_source: str
    product_external_id: str
    product_sku: str
    product_name: str
    movement_type: str
    quantity: Decimal
    unit_price: Decimal = Decimal("0.00")
    created_at: datetime


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
    company_ids: list[int] = Field(default_factory=list)


class CompanyRead(BaseModel):
    id: int
    code: str
    name: str
    company_kind: str = "matrix"
    parent_company_id: int | None = None
    active: bool = True


class CompanyLinkUpdate(BaseModel):
    company_ids: list[int] = Field(default_factory=list)


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


class CustomerProfilePaymentRuleBase(BaseModel):
    payment_method: str = "avista"
    max_installments: int = 1
    max_total_days: int = 0
    active: bool = True


class CustomerProfilePaymentRuleRead(CustomerProfilePaymentRuleBase):
    id: int

    class Config:
        from_attributes = True


class CustomerProfileCreate(CustomerProfileBase):
    payment_rules: list[CustomerProfilePaymentRuleBase] = Field(default_factory=list)


class CustomerProfileUpdate(CustomerProfileBase):
    payment_rules: list[CustomerProfilePaymentRuleBase] = Field(default_factory=list)


class CustomerProfileRead(CustomerProfileBase):
    id: int
    payment_rules: list[CustomerProfilePaymentRuleRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


class CustomerProfileAssign(BaseModel):
    customer_profile_id: int


class CustomerAlertRead(BaseModel):
    segment: str
    severity: str
    message: str
    suggested_action: str | None = None


class CustomerMonitoringRead(BaseModel):
    customer_id: str
    customer_name: str
    source: str
    current_profile_id: int | None = None
    current_profile_name: str | None = None
    suggested_profile_id: int | None = None
    suggested_profile_name: str | None = None
    health_status: str
    days_without_movement: int | None = None
    oldest_overdue_days: int = 0
    alerts: list[CustomerAlertRead] = Field(default_factory=list)


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
    company_ids: list[int] = Field(default_factory=list)

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


class PriceTableItemTierBase(BaseModel):
    min_quantity: Decimal
    discount_percent: Decimal = Decimal("0.00")
    active: bool = True


class PriceTableItemTierCreate(PriceTableItemTierBase):
    pass


class PriceTableItemTierUpdate(PriceTableItemTierBase):
    pass


class PriceTableItemTierRead(PriceTableItemTierBase):
    id: int
    price_table_item_id: int

    class Config:
        from_attributes = True


class PriceTableItemRead(PriceTableItemBase):
    id: int
    price_table_id: int
    product_sku: str | None = None
    product_name: str | None = None
    tiers: list[PriceTableItemTierRead] = Field(default_factory=list)

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
    quantity: Decimal = Decimal("1.00")
    progressive_discount_percent: Decimal = Decimal("0.00")
    progressive_tier_min_quantity: Decimal | None = None
    price_before_progressive_discount: Decimal | None = None


class SalesOrderItemCreate(BaseModel):
    product_id: int
    warehouse_id: int | None = None
    quantity: Decimal
    negotiated_unit_price: Decimal | None = None


class SalesOrderItemCancel(BaseModel):
    quantity: Decimal


class SalesOrderCreate(BaseModel):
    customer_id: str
    price_table_id: int
    order_type: str = "sale"
    order_date: date
    payment_due_date: date
    delivery_date: date | None = None
    notes: str | None = None
    items: list[SalesOrderItemCreate] = Field(default_factory=list)


class SalesOrderUpdate(SalesOrderCreate):
    pass


class SalesOrderItemRead(BaseModel):
    id: int
    company_id: int | None = None
    product_id: int
    product_sku: str
    product_name: str
    warehouse_id: int | None = None
    warehouse_name: str | None = None
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


class SalesOrderPaymentBase(BaseModel):
    payment_method: str = "boleto"
    due_date: date
    amount: Decimal
    notes: str | None = None


class SalesOrderPaymentCreate(SalesOrderPaymentBase):
    pass


class SalesOrderPaymentRead(SalesOrderPaymentBase):
    id: int
    company_id: int | None = None

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
    company_id: int | None = None
    order_number: str
    order_type: str = "sale"
    customer_source: str
    customer_external_id: str
    customer_name: str
    price_table_id: int
    price_table_name: str | None = None
    order_date: date
    payment_due_date: date
    delivery_date: date | None = None
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
    payment_suggestions: list[SalesOrderPaymentRead] = Field(default_factory=list)
    items: list[SalesOrderItemRead] = Field(default_factory=list)

    class Config:
        from_attributes = True

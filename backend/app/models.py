from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProductGroup(Base):
    __tablename__ = "sf_product_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProductClass(Base):
    __tablename__ = "sf_product_classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    product_group_id: Mapped[int | None] = mapped_column(ForeignKey("sf_product_groups.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class Product(Base):
    __tablename__ = "sf_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    product_group_id: Mapped[int | None] = mapped_column(ForeignKey("sf_product_groups.id"), nullable=True)
    product_class_id: Mapped[int | None] = mapped_column(ForeignKey("sf_product_classes.id"), nullable=True)
    sku: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="UN")
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    sale_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    description: Mapped[str | None] = mapped_column(String(800), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class CustomerLink(Base):
    __tablename__ = "sf_customer_links"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_sf_customer_source_external"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    customer_profile_id: Mapped[int | None] = mapped_column(ForeignKey("sf_customer_profiles.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="local")
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    document_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(180), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class CustomerProfile(Base):
    __tablename__ = "sf_customer_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    max_inactive_days: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    max_overdue_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    block_without_movement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    block_overdue_titles: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PriceTable(Base):
    __tablename__ = "sf_price_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    correction_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="outside")
    monthly_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    base_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PriceTableItem(Base):
    __tablename__ = "sf_price_table_items"
    __table_args__ = (UniqueConstraint("price_table_id", "product_id", name="uq_sf_price_table_product"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    price_table_id: Mapped[int] = mapped_column(ForeignKey("sf_price_tables.id"), index=True, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("sf_products.id"), index=True, nullable=False)
    base_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SalesOrder(Base):
    __tablename__ = "sf_sales_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_number: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    customer_source: Mapped[str] = mapped_column(String(40), nullable=False)
    customer_external_id: Mapped[str] = mapped_column(String(80), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(180), nullable=False)
    price_table_id: Mapped[int] = mapped_column(ForeignKey("sf_price_tables.id"), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    payment_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    approval_stage: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    approval_notes: Mapped[str | None] = mapped_column(String(800), nullable=True)
    financial_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    commercial_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_cost_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    gross_profit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    profitability_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String(800), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SalesOrderItem(Base):
    __tablename__ = "sf_sales_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sf_sales_orders.id"), index=True, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("sf_products.id"), nullable=False)
    product_sku: Mapped[str] = mapped_column(String(60), nullable=False)
    product_name: Mapped[str] = mapped_column(String(180), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    base_unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    corrected_unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    cost_unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_cost_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    gross_profit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    profitability_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

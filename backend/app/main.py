from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, engine, get_db
from app.models import (
    Company,
    CustomerLink,
    CustomerProfile,
    CustomerProfilePaymentRule,
    PriceTable,
    PriceTableItem,
    PriceTableItemTier,
    Product,
    ProductClass,
    ProductGroup,
    SalesOrder,
    SalesOrderItem,
    SalesOrderPayment,
)
from app.schemas import (
    CompanyLinkUpdate,
    CompanyRead,
    CustomerCreate,
    CustomerMonitoringRead,
    CustomerProfileAssign,
    CustomerProfileCreate,
    CustomerProfileRead,
    CustomerProfileUpdate,
    CustomerRead,
    CustomerUpdate,
    PricePreviewRead,
    PriceTableCreate,
    PriceTableItemCreate,
    PriceTableItemRead,
    PriceTableItemTierCreate,
    PriceTableItemTierRead,
    PriceTableItemTierUpdate,
    PriceTableItemUpdate,
    PriceTableRead,
    PriceTableUpdate,
    ProductClassCreate,
    ProductClassRead,
    ProductClassUpdate,
    ProductCreate,
    ProductGroupCreate,
    ProductGroupRead,
    ProductGroupUpdate,
    ProductLotConfigUpdate,
    ProductRead,
    ProductUpdate,
    SalesOrderCreate,
    SalesOrderItemCancel,
    SalesOrderItemCreate,
    SalesOrderRead,
    SalesOrderPaymentCreate,
    SalesOrderUpdate,
    StockBalanceRead,
    StockMovementRead,
)


settings = get_settings()
app = FastAPI(
    title="EasySales API",
    version="0.1.0",
    description=(
        "Produto comercial separado, operando isolado ou integrado ao ecossistema Insights X. "
        "Quando integrado ao EasyFinance, compartilha clientes pela tabela people e mantem suas "
        "proprias tabelas com prefixo sf_."
    ),
    openapi_tags=[
        {"name": "Sistema", "description": "Saude e informacoes da API."},
        {"name": "Clientes", "description": "Clientes locais ou compartilhados por conectores como EasyFinance."},
        {"name": "Perfis comerciais", "description": "Classificacao configuravel do cliente e regras de aprovacao financeira."},
        {"name": "Produtos", "description": "Catalogo comercial com preco de compra, custo e preco de referencia."},
        {"name": "Tabelas de preco", "description": "Cabecalho e itens de preco por produto, com correcao por dentro ou por fora."},
        {"name": "Pedidos", "description": "Cabecalho e itens de pedido, com preco corrigido e rentabilidade."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:5190", "http://localhost:5190"],
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost|(?:10|172|192)\.\d{1,3}\.\d{1,3}\.\d{1,3}):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS control_companies (id SERIAL PRIMARY KEY, parent_company_id INTEGER REFERENCES control_companies(id), code VARCHAR(40) UNIQUE NOT NULL, name VARCHAR(160) NOT NULL, legal_name VARCHAR(180), document_number VARCHAR(40), company_kind VARCHAR(20) NOT NULL DEFAULT 'matrix', active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO control_companies (code, name, company_kind, active) SELECT 'MATRIZ', 'Matriz', 'matrix', TRUE WHERE NOT EXISTS (SELECT 1 FROM control_companies)"))
        default_company_id = connection.execute(text("SELECT id FROM control_companies WHERE active = TRUE ORDER BY id LIMIT 1")).scalar()
        connection.execute(text("CREATE TABLE IF NOT EXISTS control_product_companies (id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES control_companies(id), product_source VARCHAR(40) NOT NULL, product_external_id VARCHAR(80) NOT NULL, default_warehouse_id INTEGER, active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT uq_control_product_company UNIQUE (product_source, product_external_id, company_id))"))
        connection.execute(text("ALTER TABLE control_product_companies ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP"))
        connection.execute(text("ALTER TABLE control_product_companies ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_control_product_companies_company_product ON control_product_companies (company_id, product_source, product_external_id)"))
        connection.execute(text("CREATE TABLE IF NOT EXISTS control_person_companies (id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES control_companies(id), person_source VARCHAR(40) NOT NULL, person_external_id VARCHAR(80) NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT uq_control_person_company UNIQUE (person_source, person_external_id, company_id))"))
        connection.execute(text("ALTER TABLE control_person_companies ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP"))
        connection.execute(text("ALTER TABLE control_person_companies ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_control_person_companies_company_person ON control_person_companies (company_id, person_source, person_external_id)"))
        connection.execute(text("CREATE TABLE IF NOT EXISTS control_catalog_companies (id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES control_companies(id), catalog_key VARCHAR(80) NOT NULL, record_id VARCHAR(80) NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT uq_control_catalog_company UNIQUE (catalog_key, record_id, company_id))"))
        connection.execute(text("ALTER TABLE control_catalog_companies ALTER COLUMN created_at SET DEFAULT CURRENT_TIMESTAMP"))
        connection.execute(text("ALTER TABLE control_catalog_companies ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_control_catalog_companies_company_record ON control_catalog_companies (company_id, catalog_key, record_id)"))
        connection.execute(text("ALTER TABLE sf_products ADD COLUMN IF NOT EXISTS purchase_price NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_products ADD COLUMN IF NOT EXISTS cost_price NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_products ADD COLUMN IF NOT EXISTS default_warehouse_id INTEGER"))
        connection.execute(text("ALTER TABLE sf_products ADD COLUMN IF NOT EXISTS default_warehouse_name VARCHAR(160)"))
        connection.execute(text("CREATE TABLE IF NOT EXISTS flow_product_lot_configs (id SERIAL PRIMARY KEY, product_source VARCHAR(40) NOT NULL, product_external_id VARCHAR(80) NOT NULL, controls_lot BOOLEAN NOT NULL DEFAULT FALSE, lot_type VARCHAR(30) NOT NULL DEFAULT 'none', updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_flow_product_lot_configs_product_external_id ON flow_product_lot_configs (product_external_id)"))
        connection.execute(text("ALTER TABLE sf_customer_links ADD COLUMN IF NOT EXISTS customer_profile_id INTEGER"))
        connection.execute(text("ALTER TABLE people ADD COLUMN IF NOT EXISTS credit_limit NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS total_cost_amount NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS gross_profit_amount NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS profitability_percent NUMERIC(10, 4) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS approval_stage VARCHAR(30) NOT NULL DEFAULT 'draft'"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS approval_notes VARCHAR(800)"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS order_type VARCHAR(20) NOT NULL DEFAULT 'sale'"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS operation_type_id INTEGER"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS operation_code VARCHAR(40)"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS delivery_date DATE"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS warehouse_id INTEGER"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS warehouse_name VARCHAR(160)"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS financial_approved_at TIMESTAMP"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS commercial_approved_at TIMESTAMP"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES control_companies(id)"))
        connection.execute(text("UPDATE sf_sales_orders SET company_id = :company_id WHERE company_id IS NULL"), {"company_id": default_company_id})
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_sf_sales_orders_company_status ON sf_sales_orders (company_id, status, approval_stage)"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS warehouse_id INTEGER"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES control_companies(id)"))
        connection.execute(text("UPDATE sf_sales_order_items SET company_id = COALESCE((SELECT o.company_id FROM sf_sales_orders o WHERE o.id = sf_sales_order_items.order_id), :company_id) WHERE company_id IS NULL"), {"company_id": default_company_id})
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_sf_sales_order_items_company_product ON sf_sales_order_items (company_id, product_id)"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS warehouse_name VARCHAR(160)"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS cost_unit_price NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS total_cost_amount NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS gross_profit_amount NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS profitability_percent NUMERIC(10, 4) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_price_table_items ADD COLUMN IF NOT EXISTS margin_percent NUMERIC(10, 4) NOT NULL DEFAULT 5"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS cancelled_quantity NUMERIC(14, 4) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS negotiated_unit_price NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS price_margin_percent NUMERIC(10, 4) NOT NULL DEFAULT 5"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS min_unit_price NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS max_unit_price NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS commercial_status VARCHAR(30) NOT NULL DEFAULT 'approved'"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS commercial_reason VARCHAR(800)"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS cancellation_status VARCHAR(30) NOT NULL DEFAULT 'active'"))
        connection.execute(text("ALTER TABLE flow_balance_ledger ALTER COLUMN stock_movement_id DROP NOT NULL"))
        connection.execute(text("ALTER TABLE sf_sales_order_payments ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES control_companies(id)"))
        connection.execute(text("UPDATE sf_sales_order_payments SET company_id = COALESCE((SELECT o.company_id FROM sf_sales_orders o WHERE o.id = sf_sales_order_payments.order_id), :company_id) WHERE company_id IS NULL"), {"company_id": default_company_id})
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_sf_sales_order_payments_company_id ON sf_sales_order_payments (company_id)"))
        connection.execute(text("ALTER TABLE flow_balance_ledger ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES control_companies(id)"))
        connection.execute(text("UPDATE flow_balance_ledger SET company_id = COALESCE((SELECT o.company_id FROM sf_sales_orders o WHERE CAST(o.id AS VARCHAR) = flow_balance_ledger.source_document_id AND flow_balance_ledger.source_system = 'easysales' AND flow_balance_ledger.source_document_kind = 'sales_order'), :company_id) WHERE company_id IS NULL"), {"company_id": default_company_id})
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_flow_balance_ledger_company_product_warehouse ON flow_balance_ledger (company_id, product_source, product_external_id, warehouse_id, balance_type_id)"))
        connection.execute(text("ALTER TABLE flow_balance_ledger ADD COLUMN IF NOT EXISTS source_system VARCHAR(40)"))
        connection.execute(text("ALTER TABLE flow_balance_ledger ADD COLUMN IF NOT EXISTS source_document_kind VARCHAR(40)"))
        connection.execute(text("ALTER TABLE flow_balance_ledger ADD COLUMN IF NOT EXISTS source_document_id VARCHAR(80)"))
        connection.execute(text("ALTER TABLE flow_balance_ledger ADD COLUMN IF NOT EXISTS source_item_id VARCHAR(80)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_flow_balance_ledger_source_item ON flow_balance_ledger (source_system, source_document_kind, source_item_id)"))
        connection.execute(text("UPDATE sf_sales_orders SET operation_code = 'PV' WHERE order_type = 'sale' AND (operation_code IS NULL OR operation_code = '')"))
        connection.execute(text("UPDATE sf_sales_orders o SET operation_type_id = op.id FROM flow_operation_types op WHERE op.code = 'PV' AND o.order_type = 'sale' AND o.operation_type_id IS NULL"))
        connection.execute(text("UPDATE sf_sales_order_items SET negotiated_unit_price = corrected_unit_price WHERE negotiated_unit_price = 0"))
        connection.execute(text("UPDATE sf_sales_order_items SET min_unit_price = ROUND(corrected_unit_price * 0.95, 2) WHERE min_unit_price = 0"))
        connection.execute(text("UPDATE sf_sales_order_items SET max_unit_price = ROUND(corrected_unit_price * 1.05, 2) WHERE max_unit_price = 0"))
        connection.execute(text("UPDATE sf_sales_orders SET order_type = 'sale' WHERE order_type IS NULL OR order_type = ''"))
        connection.execute(text("INSERT INTO control_product_companies (company_id, product_source, product_external_id, default_warehouse_id, active) SELECT :company_id, 'easysales', CAST(p.id AS VARCHAR), p.default_warehouse_id, TRUE FROM sf_products p WHERE NOT EXISTS (SELECT 1 FROM control_product_companies pc WHERE pc.company_id = :company_id AND pc.product_source = 'easysales' AND pc.product_external_id = CAST(p.id AS VARCHAR))"), {"company_id": default_company_id})
        connection.execute(text("INSERT INTO control_person_companies (company_id, person_source, person_external_id, active) SELECT :company_id, source, COALESCE(external_id, CAST(id AS VARCHAR)), TRUE FROM sf_customer_links c WHERE NOT EXISTS (SELECT 1 FROM control_person_companies pc WHERE pc.company_id = :company_id AND pc.person_source = c.source AND pc.person_external_id = COALESCE(c.external_id, CAST(c.id AS VARCHAR)))"), {"company_id": default_company_id})
        connection.execute(text("INSERT INTO control_person_companies (company_id, person_source, person_external_id, active) SELECT :company_id, 'easyfinance', CAST(p.id AS VARCHAR), TRUE FROM people p WHERE p.is_customer = TRUE AND NOT EXISTS (SELECT 1 FROM control_person_companies pc WHERE pc.company_id = :company_id AND pc.person_source = 'easyfinance' AND pc.person_external_id = CAST(p.id AS VARCHAR))"), {"company_id": default_company_id})
        connection.execute(text("INSERT INTO control_catalog_companies (company_id, catalog_key, record_id, active) SELECT :company_id, 'sf_product_groups', CAST(id AS VARCHAR), TRUE FROM sf_product_groups g WHERE NOT EXISTS (SELECT 1 FROM control_catalog_companies cc WHERE cc.company_id = :company_id AND cc.catalog_key = 'sf_product_groups' AND cc.record_id = CAST(g.id AS VARCHAR))"), {"company_id": default_company_id})
        connection.execute(text("INSERT INTO control_catalog_companies (company_id, catalog_key, record_id, active) SELECT :company_id, 'sf_product_classes', CAST(id AS VARCHAR), TRUE FROM sf_product_classes c WHERE NOT EXISTS (SELECT 1 FROM control_catalog_companies cc WHERE cc.company_id = :company_id AND cc.catalog_key = 'sf_product_classes' AND cc.record_id = CAST(c.id AS VARCHAR))"), {"company_id": default_company_id})
        connection.execute(text("INSERT INTO control_catalog_companies (company_id, catalog_key, record_id, active) SELECT :company_id, 'sf_price_tables', CAST(id AS VARCHAR), TRUE FROM sf_price_tables pt WHERE NOT EXISTS (SELECT 1 FROM control_catalog_companies cc WHERE cc.company_id = :company_id AND cc.catalog_key = 'sf_price_tables' AND cc.record_id = CAST(pt.id AS VARCHAR))"), {"company_id": default_company_id})
    seed_customer_profiles()
    db = next(get_db())
    try:
        for order in db.scalars(select(SalesOrder).where(SalesOrder.approval_stage != "draft")).all():
            sync_order_balance_ledger(db, order, strict=False)
        db.commit()
    finally:
        db.close()


def normalize_code(value: str, field_name: str = "Codigo") -> str:
    code = value.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail=f"{field_name} e obrigatorio")
    return code


def default_company_id(db: Session) -> int:
    company_id = db.scalar(select(Company.id).where(Company.active == True).order_by(Company.id.asc()))
    if not company_id:
        company = Company(code="MATRIZ", name="Matriz", company_kind="matrix", active=True)
        db.add(company)
        db.flush()
        return company.id
    return company_id


def active_company_id(request: Request, db: Session) -> int:
    raw = request.headers.get("X-Company-Id") or request.query_params.get("company_id")
    company_id = int(raw) if raw else default_company_id(db)
    company = db.get(Company, company_id)
    if not company or not company.active:
        raise HTTPException(status_code=400, detail="Empresa ativa invalida")
    return company.id


def company_ids_for_product(db: Session, product_id: int) -> list[int]:
    return [int(row) for row in db.execute(
        text(
            """
            SELECT company_id
            FROM control_product_companies
            WHERE product_source = 'easysales' AND product_external_id = :product_id AND active = TRUE
            ORDER BY company_id
            """
        ),
        {"product_id": str(product_id)},
    ).scalars().all()]


def company_ids_for_person(db: Session, source: str, external_id: str) -> list[int]:
    return [int(row) for row in db.execute(
        text(
            """
            SELECT company_id
            FROM control_person_companies
            WHERE person_source = :source AND person_external_id = :external_id AND active = TRUE
            ORDER BY company_id
            """
        ),
        {"source": source, "external_id": str(external_id)},
    ).scalars().all()]


def ensure_product_company(db: Session, company_id: int, product_id: int, default_warehouse_id: int | None = None):
    db.execute(
        text(
            """
            INSERT INTO control_product_companies (company_id, product_source, product_external_id, default_warehouse_id, active, created_at, updated_at)
            VALUES (:company_id, 'easysales', :product_id, :default_warehouse_id, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (product_source, product_external_id, company_id)
            DO UPDATE SET active = TRUE, default_warehouse_id = COALESCE(EXCLUDED.default_warehouse_id, control_product_companies.default_warehouse_id), updated_at = CURRENT_TIMESTAMP
            """
        ),
        {"company_id": company_id, "product_id": str(product_id), "default_warehouse_id": default_warehouse_id},
    )


def replace_product_companies(db: Session, product_id: int, company_ids: list[int], default_warehouse_id: int | None = None):
    if not company_ids:
        raise HTTPException(status_code=400, detail="Informe pelo menos uma empresa")
    valid_count = db.scalar(select(func.count(Company.id)).where(Company.id.in_(company_ids), Company.active == True))
    if valid_count != len(set(company_ids)):
        raise HTTPException(status_code=400, detail="Empresa invalida na lista")
    db.execute(
        text("UPDATE control_product_companies SET active = FALSE, updated_at = CURRENT_TIMESTAMP WHERE product_source = 'easysales' AND product_external_id = :product_id"),
        {"product_id": str(product_id)},
    )
    for company_id in sorted(set(company_ids)):
        ensure_product_company(db, company_id, product_id, default_warehouse_id)


def ensure_person_company(db: Session, company_id: int, source: str, external_id: str):
    db.execute(
        text(
            """
            INSERT INTO control_person_companies (company_id, person_source, person_external_id, active, created_at, updated_at)
            VALUES (:company_id, :source, :external_id, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (person_source, person_external_id, company_id)
            DO UPDATE SET active = TRUE, updated_at = CURRENT_TIMESTAMP
            """
        ),
        {"company_id": company_id, "source": source, "external_id": str(external_id)},
    )


def replace_person_companies(db: Session, source: str, external_id: str, company_ids: list[int]):
    if not company_ids:
        raise HTTPException(status_code=400, detail="Informe pelo menos uma empresa")
    valid_count = db.scalar(select(func.count(Company.id)).where(Company.id.in_(company_ids), Company.active == True))
    if valid_count != len(set(company_ids)):
        raise HTTPException(status_code=400, detail="Empresa invalida na lista")
    db.execute(
        text("UPDATE control_person_companies SET active = FALSE, updated_at = CURRENT_TIMESTAMP WHERE person_source = :source AND person_external_id = :external_id"),
        {"source": source, "external_id": str(external_id)},
    )
    for company_id in sorted(set(company_ids)):
        ensure_person_company(db, company_id, source, external_id)


def catalog_company_ids(db: Session, catalog_key: str, record_id: str | int) -> list[int]:
    rows = db.execute(
        text(
            """
            SELECT company_id
            FROM control_catalog_companies
            WHERE catalog_key = :catalog_key AND record_id = :record_id AND active = TRUE
            ORDER BY company_id
            """
        ),
        {"catalog_key": catalog_key, "record_id": str(record_id)},
    ).scalars().all()
    return [int(row) for row in rows]


def ensure_catalog_company(db: Session, company_id: int, catalog_key: str, record_id: str | int):
    db.execute(
        text(
            """
            INSERT INTO control_catalog_companies (company_id, catalog_key, record_id, active, created_at, updated_at)
            VALUES (:company_id, :catalog_key, :record_id, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (catalog_key, record_id, company_id)
            DO UPDATE SET active = TRUE, updated_at = CURRENT_TIMESTAMP
            """
        ),
        {"company_id": company_id, "catalog_key": catalog_key, "record_id": str(record_id)},
    )


def replace_catalog_companies(db: Session, catalog_key: str, record_id: str | int, company_ids: list[int]):
    if not company_ids:
        raise HTTPException(status_code=400, detail="Informe pelo menos uma empresa")
    valid_count = db.scalar(select(func.count(Company.id)).where(Company.id.in_(company_ids), Company.active == True))
    if valid_count != len(set(company_ids)):
        raise HTTPException(status_code=400, detail="Empresa invalida na lista")
    db.execute(
        text("UPDATE control_catalog_companies SET active = FALSE, updated_at = CURRENT_TIMESTAMP WHERE catalog_key = :catalog_key AND record_id = :record_id"),
        {"catalog_key": catalog_key, "record_id": str(record_id)},
    )
    for company_id in sorted(set(company_ids)):
        ensure_catalog_company(db, company_id, catalog_key, record_id)


def catalog_available_for_company(db: Session, company_id: int, catalog_key: str, record_id: str | int) -> bool:
    return bool(db.execute(
        text(
            """
            SELECT 1
            FROM control_catalog_companies
            WHERE company_id = :company_id
              AND catalog_key = :catalog_key
              AND record_id = :record_id
              AND active = TRUE
            """
        ),
        {"company_id": company_id, "catalog_key": catalog_key, "record_id": str(record_id)},
    ).first())


def product_available_for_company(db: Session, company_id: int, product_id: int) -> bool:
    return bool(db.execute(
        text(
            """
            SELECT 1 FROM control_product_companies
            WHERE company_id = :company_id AND product_source = 'easysales' AND product_external_id = :product_id AND active = TRUE
            """
        ),
        {"company_id": company_id, "product_id": str(product_id)},
    ).first())


def person_available_for_company(db: Session, company_id: int, source: str, external_id: str) -> bool:
    return bool(db.execute(
        text(
            """
            SELECT 1 FROM control_person_companies
            WHERE company_id = :company_id AND person_source = :source AND person_external_id = :external_id AND active = TRUE
            """
        ),
        {"company_id": company_id, "source": source, "external_id": str(external_id)},
    ).first())


def normalize_order_type(value: str | None) -> str:
    order_type = (value or "sale").strip().lower()
    if order_type not in {"sale", "purchase"}:
        raise HTTPException(status_code=400, detail="Tipo de pedido invalido")
    return order_type


def seed_customer_profiles():
    defaults = [
        ("NOVO", "Novo", "Cliente sem historico suficiente.", 90, 0, False, True),
        ("BOM", "Bom", "Cliente regular.", 180, 5, False, True),
        ("EXCELENTE", "Excelente", "Cliente com excelente historico.", 365, 15, False, True),
        ("RUIM", "Ruim", "Cliente exige mais atencao financeira.", 60, 0, True, True),
        ("INATIVO", "Inativo", "Cliente sem movimentacao recente.", 30, 0, True, True),
    ]
    with Session(engine) as db:
        for code, name, description, inactive_days, overdue_days, block_inactive, block_overdue in defaults:
            exists = db.scalar(select(CustomerProfile).where(CustomerProfile.code == code))
            if not exists:
                db.add(
                    CustomerProfile(
                        code=code,
                        name=name,
                        description=description,
                        max_inactive_days=inactive_days,
                        max_overdue_days=overdue_days,
                        block_without_movement=block_inactive,
                        block_overdue_titles=block_overdue,
                        active=True,
                    )
                )
        db.commit()


def get_profile_or_404(db: Session, profile_id: int | None) -> CustomerProfile | None:
    if not profile_id:
        raise HTTPException(status_code=400, detail="Informe o perfil comercial do cliente")
    item = db.get(CustomerProfile, profile_id)
    if not item:
        raise HTTPException(status_code=404, detail="Perfil comercial nao encontrado")
    return item


def customer_link_for(db: Session, source: str, external_id: str) -> CustomerLink | None:
    return db.scalar(select(CustomerLink).where(CustomerLink.source == source, CustomerLink.external_id == external_id))


def customer_profile_name(db: Session, profile_id: int | None) -> str | None:
    profile = db.get(CustomerProfile, profile_id) if profile_id else None
    return profile.name if profile else None


def profile_by_code(db: Session, code: str) -> CustomerProfile | None:
    return db.scalar(select(CustomerProfile).where(CustomerProfile.code == code))


def customer_monitoring_row(
    db: Session,
    customer_id: str,
    source: str,
    external_id: str,
    name: str,
    current_profile_id: int | None,
) -> dict:
    alerts = []
    current_profile = db.get(CustomerProfile, current_profile_id) if current_profile_id else None
    suggested_profile = current_profile
    financial = easyfinance_customer_financial(db, external_id) if source == "easyfinance" else {
        "oldest_overdue_days": 0,
        "days_without_movement": None,
    }
    days_without_movement = financial["days_without_movement"]
    oldest_overdue_days = financial["oldest_overdue_days"]

    if days_without_movement is None:
        alerts.append({
            "segment": "commercial",
            "severity": "warning",
            "message": "Cliente sem historico de movimentacao financeira.",
            "suggested_action": "Classificar como Novo ate criar historico.",
        })
        suggested_profile = profile_by_code(db, "NOVO") or suggested_profile
    elif current_profile and days_without_movement > current_profile.max_inactive_days:
        alerts.append({
            "segment": "commercial",
            "severity": "critical" if current_profile.block_without_movement else "warning",
            "message": f"Cliente sem movimentacao ha {days_without_movement} dia(s), acima do perfil atual.",
            "suggested_action": "Revisar abordagem comercial e considerar perfil Inativo.",
        })
        suggested_profile = profile_by_code(db, "INATIVO") or suggested_profile

    if current_profile and oldest_overdue_days > current_profile.max_overdue_days:
        alerts.append({
            "segment": "financial",
            "severity": "critical" if current_profile.block_overdue_titles else "warning",
            "message": f"Cliente possui titulo vencido ha {oldest_overdue_days} dia(s), acima da tolerancia do perfil.",
            "suggested_action": "Acionar financeiro antes de nova venda e considerar perfil Ruim.",
        })
        suggested_profile = profile_by_code(db, "RUIM") or suggested_profile

    if not current_profile:
        alerts.append({
            "segment": "commercial",
            "severity": "critical",
            "message": "Cliente sem perfil comercial definido.",
            "suggested_action": "Definir perfil para permitir operacao comercial.",
        })
        suggested_profile = profile_by_code(db, "NOVO") or suggested_profile

    if alerts:
        health_status = "critical" if any(row["severity"] == "critical" for row in alerts) else "attention"
    else:
        health_status = "healthy"

    return {
        "customer_id": customer_id,
        "customer_name": name,
        "source": source,
        "current_profile_id": current_profile.id if current_profile else None,
        "current_profile_name": current_profile.name if current_profile else None,
        "suggested_profile_id": suggested_profile.id if suggested_profile else None,
        "suggested_profile_name": suggested_profile.name if suggested_profile else None,
        "health_status": health_status,
        "days_without_movement": days_without_movement,
        "oldest_overdue_days": oldest_overdue_days,
        "alerts": alerts,
    }


def get_group_or_404(db: Session, group_id: int | None) -> ProductGroup | None:
    if not group_id:
        return None
    group = db.get(ProductGroup, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Grupo de produto nao encontrado")
    return group


def get_class_or_404(db: Session, class_id: int | None) -> ProductClass | None:
    if not class_id:
        return None
    item = db.get(ProductClass, class_id)
    if not item:
        raise HTTPException(status_code=404, detail="Classe de produto nao encontrada")
    return item


def class_to_read(db: Session, item: ProductClass) -> dict:
    group = db.get(ProductGroup, item.product_group_id) if item.product_group_id else None
    return {
        "id": item.id,
        "product_group_id": item.product_group_id,
        "product_group_name": group.name if group else None,
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "active": item.active,
        "company_ids": catalog_company_ids(db, "sf_product_classes", item.id),
    }


def group_to_read(db: Session, item: ProductGroup) -> dict:
    return {
        "id": item.id,
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "active": item.active,
        "company_ids": catalog_company_ids(db, "sf_product_groups", item.id),
    }


def product_to_read(db: Session, item: Product) -> dict:
    group = db.get(ProductGroup, item.product_group_id) if item.product_group_id else None
    product_class = db.get(ProductClass, item.product_class_id) if item.product_class_id else None
    lot_config = product_lot_config(db, str(item.id))
    return {
        "id": item.id,
        "product_group_id": item.product_group_id,
        "product_group_name": group.name if group else None,
        "product_class_id": item.product_class_id,
        "product_class_name": product_class.name if product_class else None,
        "sku": item.sku,
        "name": item.name,
        "unit": item.unit,
        "purchase_price": item.purchase_price,
        "cost_price": item.cost_price,
        "sale_price": item.sale_price,
        "default_warehouse_id": item.default_warehouse_id,
        "default_warehouse_name": item.default_warehouse_name,
        "controls_lot": bool(lot_config["controls_lot"]) if lot_config else False,
        "lot_type": lot_config["lot_type"] if lot_config else "none",
        "description": item.description,
        "active": item.active,
        "company_ids": company_ids_for_product(db, item.id),
    }


def product_lot_config(db: Session, product_id: str) -> dict | None:
    try:
        row = db.execute(
            text(
                """
                SELECT controls_lot, lot_type
                FROM flow_product_lot_configs
                WHERE product_source = 'easysales' AND product_external_id = :product_id
                """
            ),
            {"product_id": str(product_id)},
        ).mappings().first()
    except SQLAlchemyError:
        db.rollback()
        return None
    return dict(row) if row else None


def normalize_correction_mode(value: str) -> str:
    mode = value.strip().lower()
    if mode not in {"outside", "inside"}:
        raise HTTPException(status_code=400, detail="Modo de correcao deve ser outside ou inside")
    return mode


def money_round(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def percent_round(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def profitability_percent(revenue: Decimal, profit: Decimal) -> Decimal:
    revenue = Decimal(str(revenue or 0))
    if revenue <= 0:
        return Decimal("0")
    return percent_round(Decimal(str(profit or 0)) / revenue * Decimal("100"))


def weighted_order_profitability(items: list[SalesOrderItem], total_amount: Decimal) -> Decimal:
    total_amount = Decimal(str(total_amount or 0))
    if total_amount <= 0:
        return Decimal("0")
    weighted_sum = sum(
        Decimal(str(row.profitability_percent or 0)) * Decimal(str(row.total_amount or 0))
        for row in items
    )
    return percent_round(weighted_sum / total_amount)


def get_price_table_or_404(db: Session, price_table_id: int) -> PriceTable:
    table = db.get(PriceTable, price_table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Tabela de preco nao encontrada")
    return table


def price_table_to_read(db: Session, table: PriceTable) -> dict:
    return {
        "id": table.id,
        "code": table.code,
        "name": table.name,
        "correction_mode": table.correction_mode,
        "monthly_rate": table.monthly_rate,
        "base_date": table.base_date,
        "active": table.active,
        "company_ids": catalog_company_ids(db, "sf_price_tables", table.id),
    }


def price_table_item_to_read(db: Session, item: PriceTableItem) -> dict:
    product = db.get(Product, item.product_id)
    tiers = db.scalars(
        select(PriceTableItemTier)
        .where(PriceTableItemTier.price_table_item_id == item.id)
        .order_by(PriceTableItemTier.min_quantity.asc())
    ).all()
    return {
        "id": item.id,
        "price_table_id": item.price_table_id,
        "product_id": item.product_id,
        "product_sku": product.sku if product else None,
        "product_name": product.name if product else None,
        "base_price": item.base_price,
        "margin_percent": item.margin_percent,
        "active": item.active,
        "tiers": tiers,
    }


def correction_factor(table: PriceTable, payment_due_date: date) -> Decimal:
    days = max((payment_due_date - table.base_date).days, 0)
    rate = Decimal(str(table.monthly_rate or 0)) / Decimal("100")
    period_factor = rate * Decimal(days) / Decimal("30")
    if table.correction_mode == "inside":
        if period_factor >= 1:
            raise HTTPException(status_code=400, detail="Correcao por dentro invalida para o prazo informado")
        return Decimal("1") / (Decimal("1") - period_factor)
    return Decimal("1") + period_factor


def corrected_price(table: PriceTable, base_price: Decimal, payment_due_date: date) -> Decimal:
    return money_round(Decimal(str(base_price)) * correction_factor(table, payment_due_date))


def applicable_progressive_tier(db: Session, price_item: PriceTableItem, quantity: Decimal) -> PriceTableItemTier | None:
    return db.scalar(
        select(PriceTableItemTier)
        .where(
            PriceTableItemTier.price_table_item_id == price_item.id,
            PriceTableItemTier.active == True,
            PriceTableItemTier.min_quantity <= quantity,
        )
        .order_by(PriceTableItemTier.min_quantity.desc())
    )


def apply_progressive_discount(unit_price: Decimal, tier: PriceTableItemTier | None) -> Decimal:
    if not tier:
        return money_round(unit_price)
    discount = Decimal(str(tier.discount_percent or 0)) / Decimal("100")
    return money_round(Decimal(str(unit_price)) * (Decimal("1") - discount))


def margin_bounds(unit_price: Decimal, margin_percent: Decimal) -> tuple[Decimal, Decimal]:
    margin = Decimal(str(margin_percent or 0)) / Decimal("100")
    return (
        money_round(Decimal(str(unit_price)) * (Decimal("1") - margin)),
        money_round(Decimal(str(unit_price)) * (Decimal("1") + margin)),
    )


def commercial_status_for_price(unit_price: Decimal, min_price: Decimal, max_price: Decimal) -> str:
    unit_price = Decimal(str(unit_price or 0))
    if unit_price < Decimal(str(min_price or 0)) or unit_price > Decimal(str(max_price or 0)):
        return "pending"
    return "approved"


def commercial_reason_for_price(unit_price: Decimal, min_price: Decimal, max_price: Decimal) -> str | None:
    unit_price = Decimal(str(unit_price or 0))
    min_price = Decimal(str(min_price or 0))
    max_price = Decimal(str(max_price or 0))
    if unit_price < min_price:
        return f"Preco negociado abaixo da margem minima: {unit_price} menor que {min_price}."
    if unit_price > max_price:
        return f"Preco negociado acima da margem maxima: {unit_price} maior que {max_price}."
    return None


def effective_quantity(item: SalesOrderItem) -> Decimal:
    value = Decimal(str(item.quantity or 0)) - Decimal(str(item.cancelled_quantity or 0))
    return max(value, Decimal("0"))


def order_balance_ledger_filter(order: SalesOrder):
    return {
        "source_system": "easysales",
        "source_document_kind": "sales_order",
        "source_document_id": str(order.id),
    }


def clear_order_balance_ledger(db: Session, order: SalesOrder):
    db.execute(
        text(
            """
            DELETE FROM flow_balance_ledger
            WHERE source_system = :source_system
              AND source_document_kind = :source_document_kind
              AND source_document_id = :source_document_id
            """
        ),
        order_balance_ledger_filter(order),
    )


def sales_order_operation(db: Session, order: SalesOrder):
    operation = None
    if order.operation_type_id:
        operation = db.execute(
            text("SELECT id, code, name, movement_direction FROM flow_operation_types WHERE id = :id AND active = TRUE"),
            {"id": order.operation_type_id},
        ).mappings().first()
    if not operation:
        operation = db.execute(
            text("SELECT id, code, name, movement_direction FROM flow_operation_types WHERE code = 'PV' AND active = TRUE"),
        ).mappings().first()
    if operation:
        order.operation_type_id = operation["id"]
        order.operation_code = operation["code"]
    return operation


def balance_effect_quantity(operation, effect_direction: str, quantity: Decimal) -> Decimal:
    if effect_direction == "increase":
        return quantity
    if effect_direction == "decrease":
        return -quantity
    return -quantity if operation["movement_direction"] == "exit" else quantity


def sync_order_balance_ledger(db: Session, order: SalesOrder, strict: bool = True):
    clear_order_balance_ledger(db, order)
    if order.order_type != "sale" or order.status != "approved" or order.approval_stage != "approved":
        return
    operation = sales_order_operation(db, order)
    if not operation:
        raise HTTPException(status_code=400, detail="Operacao PV nao configurada no EasyFlow")
    effects = db.execute(
        text(
            """
            SELECT e.effect_direction, b.id AS balance_type_id, b.code AS balance_code, b.name AS balance_name
            FROM flow_operation_balance_effects e
            JOIN flow_balance_types b ON b.id = e.balance_type_id
            WHERE e.operation_type_id = :operation_type_id
              AND e.active = TRUE
              AND b.active = TRUE
            """
        ),
        {"operation_type_id": operation["id"]},
    ).mappings().all()
    if not effects:
        return
    items = db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id)).all()
    for item in items:
        quantity = effective_quantity(item)
        if quantity <= 0:
            continue
        warehouse_id = item.warehouse_id
        if not warehouse_id:
            product = db.get(Product, item.product_id)
            warehouse_id = product.default_warehouse_id if product else None
        if not warehouse_id:
            if strict:
                raise HTTPException(status_code=400, detail=f"Item {item.product_sku} sem local de estoque para reservar saldo")
            continue
        for effect in effects:
            db.execute(
                text(
                    """
                    INSERT INTO flow_balance_ledger (
                        company_id, stock_movement_id, source_system, source_document_kind, source_document_id, source_item_id,
                        warehouse_id, balance_type_id, balance_code, balance_name,
                        product_source, product_external_id, product_sku, product_name, quantity, created_at
                    )
                    VALUES (
                        :company_id, NULL, 'easysales', 'sales_order', :order_id, :item_id,
                        :warehouse_id, :balance_type_id, :balance_code, :balance_name,
                        'easysales', :product_id, :product_sku, :product_name, :quantity, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "order_id": str(order.id),
                    "company_id": order.company_id,
                    "item_id": str(item.id),
                    "warehouse_id": warehouse_id,
                    "balance_type_id": effect["balance_type_id"],
                    "balance_code": effect["balance_code"],
                    "balance_name": effect["balance_name"],
                    "product_id": str(item.product_id),
                    "product_sku": item.product_sku,
                    "product_name": item.product_name,
                    "quantity": balance_effect_quantity(operation, effect["effect_direction"], quantity),
                },
            )


def linked_quantity_for_order_item(db: Session, item_id: int) -> Decimal:
    try:
        value = db.scalar(
            text(
                """
                SELECT COALESCE(SUM(quantity), 0)
                FROM flow_document_link_ledger
                WHERE source_system = 'easysales'
                  AND source_document_kind = 'sales_order'
                  AND source_item_id = :item_id
                """
            ),
            {"item_id": str(item_id)},
        )
    except SQLAlchemyError:
        value = Decimal("0")
    return Decimal(str(value or 0))


def ensure_order_item_has_editable_balance(db: Session, item: SalesOrderItem, new_quantity: Decimal | None = None, deleting: bool = False):
    linked_quantity = linked_quantity_for_order_item(db, item.id)
    current_quantity = effective_quantity(item)
    if linked_quantity <= 0:
        return
    if current_quantity - linked_quantity <= 0:
        raise HTTPException(status_code=400, detail="Item sem saldo do pedido para edicao")
    if deleting:
        raise HTTPException(status_code=400, detail="Item com baixa vinculada no Flow nao pode ser excluido")
    if new_quantity is not None and Decimal(str(new_quantity)) < linked_quantity:
        raise HTTPException(status_code=400, detail="Quantidade do item nao pode ficar menor que a quantidade ja baixada no Flow")


def recalculate_order_item(item: SalesOrderItem):
    qty = effective_quantity(item)
    unit_price = Decimal(str(item.negotiated_unit_price or item.corrected_unit_price or 0))
    item.total_amount = money_round(qty * unit_price)
    item.total_cost_amount = money_round(qty * Decimal(str(item.cost_unit_price or 0)))
    item.gross_profit_amount = money_round(item.total_amount - item.total_cost_amount)
    item.profitability_percent = profitability_percent(item.total_amount, item.gross_profit_amount)
    if qty <= 0:
        item.cancellation_status = "cancelled"
    elif Decimal(str(item.cancelled_quantity or 0)) > 0:
        item.cancellation_status = "partial"
    else:
        item.cancellation_status = "active"


def resolve_customer(db: Session, customer_id: str) -> dict:
    source, _, external_id = customer_id.partition(":")
    if not source or not external_id:
        raise HTTPException(status_code=400, detail="Cliente invalido")
    if source == "easyfinance":
        row = db.execute(
            text(
                """
                SELECT id, name, document_number, email, phone, city, state_code, active, credit_limit
                FROM people
                WHERE id = :id AND is_customer = TRUE AND active = TRUE
                """
            ),
            {"id": external_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Cliente nao encontrado")
        link = customer_link_for(db, "easyfinance", external_id)
        return {"source": source, "external_id": external_id, "name": row["name"], "profile_id": link.customer_profile_id if link else None}
    link = db.get(CustomerLink, int(external_id)) if source == "local" and external_id.isdigit() else None
    if not link or not link.active:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")
    return {"source": source, "external_id": str(link.id), "name": link.name, "profile_id": link.customer_profile_id}


def next_order_number(db: Session) -> str:
    latest_id = db.scalar(select(SalesOrder.id).order_by(SalesOrder.id.desc()))
    return f"PV-{(latest_id or 0) + 1:06d}"


def order_for_company_or_404(db: Session, order_id: int, company_id: int) -> SalesOrder:
    order = db.get(SalesOrder, order_id)
    if not order or order.company_id != company_id:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")
    return order


def resolve_warehouse(db: Session, warehouse_id: int | None) -> dict | None:
    if not warehouse_id:
        return None
    row = db.execute(
        text("SELECT id, code, name, active FROM flow_warehouses WHERE id = :id"),
        {"id": warehouse_id},
    ).mappings().first()
    if not row or not row["active"]:
        raise HTTPException(status_code=400, detail="Local de estoque inativo ou nao encontrado")
    return {"id": int(row["id"]), "name": f"{row['code']} - {row['name']}"}


def financial_authorization_reasons(db: Session, order: SalesOrder) -> list[dict]:
    if order.status not in {"pending_financial", "financial_blocked"}:
        return []
    reasons = []
    profile_id = resolve_customer(db, f"{order.customer_source}:{order.customer_external_id}").get("profile_id")
    profile = db.get(CustomerProfile, profile_id) if profile_id else None
    if order.customer_source != "easyfinance":
        return [
            {
                "segment": "financial",
                "scope": "order",
                "reason": "Cliente local sem consulta financeira integrada.",
                "status": "pending",
                "suggested_role": "financeiro",
            }
        ]
    financial = easyfinance_customer_financial(db, order.customer_external_id)
    projected_open = money_round(financial["open_amount"] + Decimal(str(order.total_amount or 0)))
    credit_limit = money_round(financial["credit_limit"])
    if projected_open > credit_limit:
        reasons.append(
            {
                "segment": "financial",
                "scope": "order",
                "reason": f"Limite de credito excedido. Limite cadastrado: {credit_limit}; aberto projetado com o pedido: {projected_open}.",
                "status": "blocked" if order.status == "financial_blocked" else "pending",
                "suggested_role": "financeiro",
            }
        )
    if not profile:
        reasons.append(
            {
                "segment": "financial",
                "scope": "order",
                "reason": "Cliente sem perfil comercial para definir tolerancias financeiras.",
                "status": "pending",
                "suggested_role": "financeiro",
            }
        )
    if profile and profile.block_overdue_titles and financial["oldest_overdue_days"] > profile.max_overdue_days:
        reasons.append(
            {
                "segment": "financial",
                "scope": "order",
                "reason": f"Titulo vencido ha {financial['oldest_overdue_days']} dia(s); perfil {profile.name} tolera ate {profile.max_overdue_days} dia(s).",
                "status": "blocked" if order.status == "financial_blocked" else "pending",
                "suggested_role": "financeiro",
            }
        )
    if profile and profile.block_without_movement:
        inactive_days = financial["days_without_movement"]
        if inactive_days is None or inactive_days > profile.max_inactive_days:
            label = "sem historico de movimentacao" if inactive_days is None else f"sem movimentacao ha {inactive_days} dia(s)"
            reasons.append(
                {
                    "segment": "financial",
                    "scope": "order",
                    "reason": f"Cliente {label}; perfil {profile.name} tolera ate {profile.max_inactive_days} dia(s).",
                    "status": "blocked" if order.status == "financial_blocked" else "pending",
                    "suggested_role": "financeiro",
                }
            )
    if not reasons:
        reasons.append(
            {
                "segment": "financial",
                "scope": "order",
                "reason": "Pedido aguardando conferencia financeira de credito e inadimplencia.",
                "status": "pending",
                "suggested_role": "financeiro",
            }
        )
    return reasons


def order_authorization_reasons(db: Session, order: SalesOrder, items: list[SalesOrderItem]) -> list[dict]:
    reasons = []
    reasons.extend(financial_authorization_reasons(db, order))
    for item in items:
        if item.commercial_status == "pending":
            reasons.append(
                {
                    "segment": "commercial",
                    "scope": "item",
                    "item_id": item.id,
                    "item_name": f"{item.product_sku} - {item.product_name}",
                    "reason": item.commercial_reason or commercial_reason_for_price(
                        item.negotiated_unit_price,
                        item.min_unit_price,
                        item.max_unit_price,
                    ) or "Item requer autorizacao comercial.",
                    "status": "pending",
                    "suggested_role": "comercial",
                }
            )
    return reasons


def order_to_read(db: Session, order: SalesOrder) -> dict:
    table = db.get(PriceTable, order.price_table_id)
    items = db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id).order_by(SalesOrderItem.id.asc())).all()
    payment_suggestions = db.scalars(select(SalesOrderPayment).where(SalesOrderPayment.order_id == order.id).order_by(SalesOrderPayment.due_date.asc(), SalesOrderPayment.id.asc())).all()
    return {
        "id": order.id,
        "company_id": order.company_id,
        "order_number": order.order_number,
        "order_type": order.order_type or "sale",
        "customer_source": order.customer_source,
        "customer_external_id": order.customer_external_id,
        "customer_name": order.customer_name,
        "price_table_id": order.price_table_id,
        "price_table_name": table.name if table else None,
        "order_date": order.order_date,
        "payment_due_date": order.payment_due_date,
        "delivery_date": order.delivery_date,
        "status": order.status,
        "approval_stage": order.approval_stage,
        "approval_notes": order.approval_notes,
        "financial_approved_at": order.financial_approved_at,
        "commercial_approved_at": order.commercial_approved_at,
        "total_amount": order.total_amount,
        "total_cost_amount": order.total_cost_amount,
        "gross_profit_amount": order.gross_profit_amount,
        "profitability_percent": order.profitability_percent,
        "notes": order.notes,
        "authorization_reasons": order_authorization_reasons(db, order, items),
        "payment_suggestions": payment_suggestions,
        "items": items,
    }


def profile_payment_rules(db: Session, profile_id: int) -> list[CustomerProfilePaymentRule]:
    return db.scalars(
        select(CustomerProfilePaymentRule)
        .where(CustomerProfilePaymentRule.customer_profile_id == profile_id)
        .order_by(CustomerProfilePaymentRule.payment_method.asc(), CustomerProfilePaymentRule.max_installments.asc(), CustomerProfilePaymentRule.max_total_days.asc())
    ).all()


def customer_profile_to_read(db: Session, item: CustomerProfile) -> dict:
    return {
        "id": item.id,
        "code": item.code,
        "name": item.name,
        "description": item.description,
        "max_inactive_days": item.max_inactive_days,
        "max_overdue_days": item.max_overdue_days,
        "block_without_movement": item.block_without_movement,
        "block_overdue_titles": item.block_overdue_titles,
        "active": item.active,
        "payment_rules": profile_payment_rules(db, item.id),
    }


def replace_profile_payment_rules(db: Session, profile: CustomerProfile, rules):
    allowed_methods = {"avista", "parcelado", "adiantamento"}
    for existing in profile_payment_rules(db, profile.id):
        db.delete(existing)
    for rule in rules:
        if rule.payment_method not in allowed_methods:
            raise HTTPException(status_code=400, detail="Condicao de pagamento invalida no perfil")
        if rule.max_installments <= 0:
            raise HTTPException(status_code=400, detail="Quantidade maxima de parcelas deve ser maior que zero")
        if rule.max_total_days < 0:
            raise HTTPException(status_code=400, detail="Dias maximos de parcelamento nao pode ser negativo")
        db.add(
            CustomerProfilePaymentRule(
                customer_profile_id=profile.id,
                payment_method=rule.payment_method,
                max_installments=rule.max_installments,
                max_total_days=rule.max_total_days,
                active=rule.active,
            )
        )


def recalculate_order_totals(db: Session, order: SalesOrder):
    db.flush()
    items = db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id)).all()
    for item in items:
        recalculate_order_item(item)
    db.flush()
    order.total_amount = money_round(sum((Decimal(str(row.total_amount)) for row in items), Decimal("0")))
    order.total_cost_amount = money_round(sum((Decimal(str(row.total_cost_amount)) for row in items), Decimal("0")))
    order.gross_profit_amount = money_round(order.total_amount - order.total_cost_amount)
    order.profitability_percent = weighted_order_profitability(items, order.total_amount)
    if items and all(effective_quantity(item) <= 0 for item in items):
        order.status = "cancelled"
        order.approval_stage = "cancelled"
        order.approval_notes = "Pedido cancelado integralmente pelos itens."


def validate_payment_suggestions(order: SalesOrder, payload: list[SalesOrderPaymentCreate]):
    if not payload:
        raise HTTPException(status_code=400, detail="Informe ao menos uma sugestao de pagamento")
    total = Decimal("0")
    allowed_methods = {"avista", "parcelado", "adiantamento"}
    for item in payload:
        if item.payment_method not in allowed_methods:
            raise HTTPException(status_code=400, detail="Condicao de pagamento invalida")
        amount = Decimal(str(item.amount or 0))
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Valor da parcela deve ser maior que zero")
        total += amount
    if money_round(total) != money_round(Decimal(str(order.total_amount or 0))):
        raise HTTPException(status_code=400, detail="Total das sugestoes de pagamento deve fechar com o total do pedido")


def easyfinance_customer_financial(db: Session, external_id: str) -> dict:
    row = db.execute(
        text(
            """
            SELECT id, credit_limit
            FROM people
            WHERE id = :id AND is_customer = TRUE
            """
        ),
        {"id": external_id},
    ).mappings().first()
    if not row:
        return {"credit_limit": Decimal("0"), "open_amount": Decimal("0"), "oldest_overdue_days": 0, "days_without_movement": None}

    open_amount = db.execute(
        text(
            """
            SELECT COALESCE(SUM(fe.amount - COALESCE(fs.paid_amount, 0)), 0) AS balance
            FROM financial_entries fe
            LEFT JOIN (
                SELECT entry_id, SUM(amount) AS paid_amount
                FROM financial_settlements
                GROUP BY entry_id
            ) fs ON fs.entry_id = fe.id
            WHERE fe.person_id = :id
              AND fe.entry_type = 'receivable'
              AND fe.active = TRUE
              AND (fe.amount - COALESCE(fs.paid_amount, 0)) > 0
            """
        ),
        {"id": external_id},
    ).scalar()
    oldest_overdue = db.execute(
        text(
            """
            SELECT MAX(CURRENT_DATE - fe.due_date) AS days
            FROM financial_entries fe
            LEFT JOIN (
                SELECT entry_id, SUM(amount) AS paid_amount
                FROM financial_settlements
                GROUP BY entry_id
            ) fs ON fs.entry_id = fe.id
            WHERE fe.person_id = :id
              AND fe.entry_type = 'receivable'
              AND fe.active = TRUE
              AND fe.due_date < CURRENT_DATE
              AND (fe.amount - COALESCE(fs.paid_amount, 0)) > 0
            """
        ),
        {"id": external_id},
    ).scalar()
    last_movement = db.execute(
        text(
            """
            SELECT MAX(movement_date) AS movement_date
            FROM (
                SELECT COALESCE(issue_date, created_at::date) AS movement_date
                FROM financial_entries
                WHERE person_id = :id AND entry_type = 'receivable'
                UNION ALL
                SELECT settlement_date AS movement_date
                FROM financial_settlements fs
                JOIN financial_entries fe ON fe.id = fs.entry_id
                WHERE fe.person_id = :id AND fe.entry_type = 'receivable'
            ) movements
            """
        ),
        {"id": external_id},
    ).scalar()
    days_without_movement = (date.today() - last_movement).days if last_movement else None
    return {
        "credit_limit": Decimal(str(row["credit_limit"] or 0)),
        "open_amount": Decimal(str(open_amount or 0)),
        "oldest_overdue_days": int(oldest_overdue or 0),
        "days_without_movement": days_without_movement,
    }


def payment_rule_notes(db: Session, order: SalesOrder, profile: CustomerProfile | None) -> list[str]:
    if not profile:
        return ["Cliente sem perfil comercial para validar condicao de pagamento."]
    rules = [
        rule for rule in profile_payment_rules(db, profile.id)
        if rule.active
    ]
    if not rules:
        return ["Perfil comercial sem condicoes de pagamento liberadas."]
    suggestions = db.scalars(select(SalesOrderPayment).where(SalesOrderPayment.order_id == order.id)).all()
    if not suggestions:
        return ["Pedido sem condicao de pagamento registrada."]
    notes: list[str] = []
    methods = sorted({item.payment_method for item in suggestions})
    for method in methods:
        rows = [item for item in suggestions if item.payment_method == method]
        installments = len(rows)
        max_total_days = max(((item.due_date - order.order_date).days for item in rows), default=0)
        max_total_days = max(max_total_days, 0)
        accepted = any(
            rule.payment_method == method
            and installments <= rule.max_installments
            and max_total_days <= rule.max_total_days
            for rule in rules
        )
        if not accepted:
            notes.append(f"Condicao de pagamento {payment_method_label(method)} em {installments} parcela(s) e {max_total_days} dia(s) nao liberada para o perfil {profile.name}.")
    return notes


def payment_method_label(method: str) -> str:
    return {"avista": "a vista", "parcelado": "parcelado", "adiantamento": "adiantamento"}.get(method, method)


def evaluate_financial_approval(db: Session, order: SalesOrder) -> tuple[bool, list[str]]:
    notes: list[str] = []
    profile_id = resolve_customer(db, f"{order.customer_source}:{order.customer_external_id}").get("profile_id")
    profile = db.get(CustomerProfile, profile_id) if profile_id else None
    if order.customer_source != "easyfinance":
        return True, ["Cliente local sem consulta financeira integrada."]
    financial = easyfinance_customer_financial(db, order.customer_external_id)
    projected_open = money_round(financial["open_amount"] + Decimal(str(order.total_amount or 0)))
    credit_limit = money_round(financial["credit_limit"])
    if projected_open > credit_limit:
        notes.append(f"Limite de credito excedido: projetado {projected_open} para limite {credit_limit}.")
    if profile and profile.block_overdue_titles and financial["oldest_overdue_days"] > profile.max_overdue_days:
        notes.append(f"Cliente possui titulo vencido ha {financial['oldest_overdue_days']} dia(s), limite do perfil {profile.max_overdue_days}.")
    if profile and profile.block_without_movement:
        inactive_days = financial["days_without_movement"]
        if inactive_days is None or inactive_days > profile.max_inactive_days:
            notes.append(f"Cliente sem movimentacao dentro de {profile.max_inactive_days} dia(s).")
    notes.extend(payment_rule_notes(db, order, profile))
    return len(notes) == 0, notes or ["Aprovacao financeira sem restricoes."]


def refresh_order_approval_stage(db: Session, order: SalesOrder):
    if order.status in {"cancelled", "rejected"}:
        return
    items = db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id)).all()
    active_items = [item for item in items if effective_quantity(item) > 0]
    if not active_items:
        order.status = "cancelled"
        order.approval_stage = "cancelled"
        order.approval_notes = "Pedido cancelado integralmente pelos itens."
        sync_order_balance_ledger(db, order)
        return
    pending = [item for item in active_items if item.commercial_status == "pending"]
    if pending:
        order.status = "pending_commercial"
        order.approval_stage = "commercial"
        order.approval_notes = "Pedido possui item(ns) que precisam de autorizacao comercial."
        sync_order_balance_ledger(db, order)
        return
    if order.status in {"pending_commercial", "financial_blocked"}:
        order.status = "approved"
        order.approval_stage = "approved"
        order.commercial_approved_at = datetime.utcnow()
        order.approval_notes = "Itens aprovados comercialmente."
    sync_order_balance_ledger(db, order)


def apply_order_approval_flow(db: Session, order: SalesOrder):
    recalculate_order_totals(db, order)
    if Decimal(str(order.total_amount or 0)) <= 0:
        raise HTTPException(status_code=400, detail="Pedido sem itens ou total zerado")
    has_payment_suggestion = db.scalar(select(SalesOrderPayment).where(SalesOrderPayment.order_id == order.id))
    if not has_payment_suggestion:
        raise HTTPException(status_code=400, detail="Registre a condicao de pagamento antes de enviar para aprovacao.")
    allowed, notes = evaluate_financial_approval(db, order)
    if not allowed:
        order.status = "financial_blocked"
        order.approval_stage = "financial"
        order.financial_approved_at = None
        order.commercial_approved_at = None
        order.approval_notes = " ".join(notes)
        sync_order_balance_ledger(db, order)
        return
    order.financial_approved_at = datetime.utcnow()
    pending_commercial = db.scalar(
        select(SalesOrderItem).where(
            SalesOrderItem.order_id == order.id,
            SalesOrderItem.commercial_status == "pending",
            SalesOrderItem.cancellation_status != "cancelled",
        )
    )
    if pending_commercial:
        order.status = "pending_commercial"
        order.approval_stage = "commercial"
        order.commercial_approved_at = None
        order.approval_notes = "Pedido aprovado financeiramente. Existem item(ns) pendentes de autorizacao comercial."
        sync_order_balance_ledger(db, order)
        return
    order.status = "approved"
    order.approval_stage = "approved"
    order.commercial_approved_at = datetime.utcnow()
    order.approval_notes = "Pedido aprovado automaticamente sem pendencias financeiras ou comerciais."
    sync_order_balance_ledger(db, order)


def revalidate_order_if_submitted(db: Session, order: SalesOrder, was_submitted: bool):
    if was_submitted and order.status not in {"cancelled", "rejected"}:
        apply_order_approval_flow(db, order)
    else:
        refresh_order_approval_stage(db, order)


def apply_payload_to_order_item(db: Session, order: SalesOrder, table: PriceTable, payload_item, item: SalesOrderItem | None = None) -> SalesOrderItem:
    if Decimal(str(payload_item.quantity)) <= 0:
        raise HTTPException(status_code=400, detail="Quantidade deve ser maior que zero")
    product = db.get(Product, payload_item.product_id)
    if not product or not product.active:
        raise HTTPException(status_code=400, detail="Produto inativo ou nao encontrado")
    if not product_available_for_company(db, order.company_id, product.id):
        raise HTTPException(status_code=400, detail=f"Produto {product.sku} nao vinculado a empresa do pedido")
    price_item = db.scalar(
        select(PriceTableItem).where(
            PriceTableItem.price_table_id == table.id,
            PriceTableItem.product_id == product.id,
            PriceTableItem.active == True,
        )
    )
    if not price_item:
        raise HTTPException(status_code=400, detail=f"Produto {product.sku} sem preco ativo na tabela")
    quantity = Decimal(str(payload_item.quantity))
    if item:
        ensure_order_item_has_editable_balance(db, item, new_quantity=quantity)
    price_before_progressive_discount = corrected_price(table, price_item.base_price, order.payment_due_date)
    progressive_tier = applicable_progressive_tier(db, price_item, quantity)
    unit_price = apply_progressive_discount(price_before_progressive_discount, progressive_tier)
    negotiated_unit_price = money_round(Decimal(str(payload_item.negotiated_unit_price or unit_price)))
    min_unit_price, max_unit_price = margin_bounds(unit_price, price_item.margin_percent)
    cost_unit_price = money_round(Decimal(str(product.cost_price or 0)))
    item_total = money_round(quantity * negotiated_unit_price)
    item_total_cost = money_round(quantity * cost_unit_price)
    item_profit = money_round(item_total - item_total_cost)
    item = item or SalesOrderItem(order_id=order.id, company_id=order.company_id, cancelled_quantity=Decimal("0"), cancellation_status="active")
    item.company_id = order.company_id
    warehouse = resolve_warehouse(db, payload_item.warehouse_id or product.default_warehouse_id)
    item.product_id = product.id
    item.product_sku = product.sku
    item.product_name = product.name
    item.warehouse_id = warehouse["id"] if warehouse else None
    item.warehouse_name = warehouse["name"] if warehouse else None
    item.quantity = quantity
    item.base_unit_price = price_item.base_price
    item.corrected_unit_price = unit_price
    item.negotiated_unit_price = negotiated_unit_price
    item.price_margin_percent = price_item.margin_percent
    item.min_unit_price = min_unit_price
    item.max_unit_price = max_unit_price
    item.cost_unit_price = cost_unit_price
    item.total_amount = item_total
    item.total_cost_amount = item_total_cost
    item.gross_profit_amount = item_profit
    item.profitability_percent = profitability_percent(item_total, item_profit)
    item.commercial_status = commercial_status_for_price(negotiated_unit_price, min_unit_price, max_unit_price)
    item.commercial_reason = commercial_reason_for_price(negotiated_unit_price, min_unit_price, max_unit_price)
    recalculate_order_item(item)
    if item.id is None:
        db.add(item)
    return item


def build_order_items(db: Session, order: SalesOrder, table: PriceTable, payload_items, payment_due_date: date):
    order.payment_due_date = payment_due_date
    for payload_item in payload_items:
        apply_payload_to_order_item(db, order, table, payload_item)


@app.get("/health", tags=["Sistema"])
def health():
    return {"ok": True, "service": "easysales", "customer_provider": settings.customer_provider}


@app.get("/companies", response_model=list[CompanyRead], tags=["Sistema"])
def list_companies(db: Session = Depends(get_db)):
    return db.scalars(select(Company).where(Company.active == True).order_by(Company.company_kind.desc(), Company.name.asc())).all()


@app.get("/control/browser-definitions", tags=["Sistema"])
def list_control_browser_definitions(db: Session = Depends(get_db)):
    try:
        rows = db.execute(
            text(
                """
                SELECT
                    b.id AS browser_id,
                    b.code AS browser_code,
                    b.name AS browser_name,
                    b.description AS browser_description,
                    b.scope AS browser_scope,
                    b.source_mode AS source_mode,
                    b.is_standard AS is_standard,
                    e.code AS entity_code,
                    e.display_name AS entity_name,
                    f.id AS field_id,
                    f.technical_name AS field_name,
                    COALESCE(c.label_override, f.display_name) AS field_label,
                    f.data_type AS field_type,
                    f.filterable AS field_filterable,
                    f.sortable AS field_sortable,
                    c.ordinal AS column_ordinal,
                    c.width AS column_width
                FROM control_browser_definitions b
                JOIN control_metadata_entities e ON e.id = b.entity_id
                LEFT JOIN control_browser_columns c ON c.browser_id = b.id AND c.active = TRUE
                LEFT JOIN control_metadata_fields f ON f.id = c.field_id AND f.active = TRUE
                WHERE b.active = TRUE
                  AND e.active = TRUE
                ORDER BY e.display_name, b.name, c.ordinal, f.display_name
                """
            )
        ).mappings().all()
    except Exception:
        return []
    browsers = {}
    for row in rows:
        browser = browsers.setdefault(
            row["browser_id"],
            {
                "id": row["browser_id"],
                "code": row["browser_code"],
                "name": row["browser_name"],
                "description": row["browser_description"],
                "scope": row["browser_scope"],
                "source_mode": row["source_mode"],
                "is_standard": row["is_standard"],
                "entity_code": row["entity_code"],
                "entity_name": row["entity_name"],
                "columns": [],
                "filters": [],
            },
        )
        if row["field_id"]:
            browser["columns"].append(
                {
                    "id": row["field_id"],
                    "name": row["field_name"],
                    "label": row["field_label"],
                    "type": row["field_type"],
                    "filterable": row["field_filterable"],
                    "sortable": row["field_sortable"],
                    "ordinal": row["column_ordinal"],
                    "width": row["column_width"],
                }
            )
    try:
        filter_rows = db.execute(
            text(
                """
                SELECT
                    bf.id,
                    bf.browser_id,
                    f.technical_name AS field_name,
                    COALESCE(f.display_name, f.technical_name) AS field_label,
                    f.data_type AS field_type,
                    bf.operator,
                    bf.value,
                    bf.value_to,
                    bf.behavior,
                    bf.value_kind,
                    bf.required,
                    bf.ordinal,
                    bf.active
                FROM control_browser_filters bf
                JOIN control_metadata_fields f ON f.id = bf.field_id
                WHERE bf.active = TRUE
                ORDER BY bf.browser_id, bf.ordinal, f.display_name
                """
            )
        ).mappings().all()
        for row in filter_rows:
            browser = browsers.get(row["browser_id"])
            if not browser:
                continue
            browser["filters"].append(
                {
                    "id": row["id"],
                    "field": row["field_name"],
                    "label": row["field_label"],
                    "type": row["field_type"],
                    "operator": row["operator"],
                    "value": row["value"],
                    "valueTo": row["value_to"],
                    "behavior": row["behavior"],
                    "valueKind": row["value_kind"],
                    "required": row["required"],
                    "ordinal": row["ordinal"],
                }
            )
    except Exception:
        pass
    return list(browsers.values())


@app.get("/customers", response_model=list[CustomerRead], tags=["Clientes"])
def list_customers(request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    local_links = db.scalars(
        select(CustomerLink)
        .where(
            CustomerLink.source == "local",
            CustomerLink.active == True,
            text("EXISTS (SELECT 1 FROM control_person_companies pc WHERE pc.company_id = :company_id AND pc.person_source = 'local' AND pc.person_external_id = CAST(sf_customer_links.id AS VARCHAR) AND pc.active = TRUE)"),
        )
        .params(company_id=company_id)
        .order_by(CustomerLink.name.asc())
    ).all()
    local_rows = [
        {
            "id": f"local:{item.id}",
            "source": item.source,
            "customer_profile_id": item.customer_profile_id,
            "customer_profile_name": customer_profile_name(db, item.customer_profile_id),
            "credit_limit": Decimal("0"),
            "name": item.name,
            "document_number": item.document_number,
            "email": item.email,
            "phone": item.phone,
            "city": item.city,
            "state_code": item.state_code,
            "active": item.active,
            "company_ids": company_ids_for_person(db, item.source, str(item.id)),
        }
        for item in local_links
    ]
    if settings.customer_provider == "easyfinance":
        try:
            rows = db.execute(
                text(
                    """
                    SELECT people.id, people.name, people.document_number, people.email, people.phone, people.city, people.state_code, people.active, people.credit_limit
                    FROM people
                    JOIN control_person_companies pc ON pc.person_source = 'easyfinance'
                        AND pc.person_external_id = CAST(people.id AS VARCHAR)
                        AND pc.company_id = :company_id
                        AND pc.active = TRUE
                    WHERE is_customer = TRUE AND active = TRUE
                    ORDER BY name ASC
                    """
                ),
                {"company_id": company_id},
            ).mappings().all()
        except SQLAlchemyError:
            db.rollback()
            rows = []
        shared_rows = [
            {
                "id": f"easyfinance:{row['id']}",
                "source": "easyfinance",
                "customer_profile_id": (link.customer_profile_id if (link := customer_link_for(db, "easyfinance", str(row["id"]))) else None),
                "customer_profile_name": customer_profile_name(db, link.customer_profile_id) if link else None,
                "credit_limit": row["credit_limit"],
                "name": row["name"],
                "document_number": row["document_number"],
                "email": row["email"],
                "phone": row["phone"],
                "city": row["city"],
                "state_code": row["state_code"],
                "active": row["active"],
                "company_ids": company_ids_for_person(db, "easyfinance", str(row["id"])),
            }
            for row in rows
        ]
        return [*shared_rows, *local_rows]

    return local_rows


@app.get("/warehouses", tags=["Locais de estoque"])
def list_warehouses(db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT id, code, name, active FROM flow_warehouses ORDER BY code ASC, name ASC")
    ).mappings().all()
    return [
        {"id": row["id"], "code": row["code"], "name": f"{row['code']} - {row['name']}", "active": row["active"]}
        for row in rows
    ]


@app.post("/customers", response_model=CustomerRead, status_code=status.HTTP_201_CREATED, tags=["Clientes"])
def create_customer(payload: CustomerCreate, request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    get_profile_or_404(db, payload.customer_profile_id)
    item = CustomerLink(
        customer_profile_id=payload.customer_profile_id,
        source="local",
        external_id=None,
        name=payload.name.strip(),
        document_number=payload.document_number,
        email=payload.email,
        phone=payload.phone,
        city=payload.city,
        state_code=payload.state_code.upper() if payload.state_code else None,
        active=payload.active,
    )
    db.add(item)
    db.flush()
    item.external_id = str(item.id)
    ensure_person_company(db, company_id, "local", str(item.id))
    db.commit()
    db.refresh(item)
    return {
        "id": f"local:{item.id}",
        "source": "local",
        "customer_profile_id": item.customer_profile_id,
        "customer_profile_name": customer_profile_name(db, item.customer_profile_id),
        "credit_limit": Decimal("0"),
        "name": item.name,
        "document_number": item.document_number,
        "email": item.email,
        "phone": item.phone,
        "city": item.city,
        "state_code": item.state_code,
        "active": item.active,
        "company_ids": company_ids_for_person(db, item.source, str(item.id)),
    }


@app.put("/customers/{customer_id}", response_model=CustomerRead, tags=["Clientes"])
def update_customer(customer_id: int, payload: CustomerUpdate, db: Session = Depends(get_db)):
    item = db.get(CustomerLink, customer_id)
    if not item or item.source != "local":
        raise HTTPException(status_code=404, detail="Cliente local nao encontrado")
    get_profile_or_404(db, payload.customer_profile_id)
    item.name = payload.name.strip()
    item.customer_profile_id = payload.customer_profile_id
    item.document_number = payload.document_number
    item.email = payload.email
    item.phone = payload.phone
    item.city = payload.city
    item.state_code = payload.state_code.upper() if payload.state_code else None
    item.active = payload.active
    db.commit()
    db.refresh(item)
    return {
        "id": f"local:{item.id}",
        "source": "local",
        "customer_profile_id": item.customer_profile_id,
        "customer_profile_name": customer_profile_name(db, item.customer_profile_id),
        "credit_limit": Decimal("0"),
        "name": item.name,
        "document_number": item.document_number,
        "email": item.email,
        "phone": item.phone,
        "city": item.city,
        "state_code": item.state_code,
        "active": item.active,
        "company_ids": company_ids_for_person(db, item.source, str(item.id)),
    }


@app.put("/customers/{source}/{external_id}/companies", response_model=list[int], tags=["Clientes"])
def update_customer_companies(source: str, external_id: str, payload: CompanyLinkUpdate, db: Session = Depends(get_db)):
    if source == "local":
        link = db.get(CustomerLink, int(external_id)) if external_id.isdigit() else None
        if not link or link.source != "local":
            raise HTTPException(status_code=404, detail="Cliente local nao encontrado")
        person_external_id = str(link.id)
    elif source == "easyfinance":
        row = db.execute(text("SELECT id FROM people WHERE id = :id AND is_customer = TRUE"), {"id": external_id}).first()
        if not row:
            raise HTTPException(status_code=404, detail="Cliente EasyFinance nao encontrado")
        person_external_id = external_id
    else:
        raise HTTPException(status_code=400, detail="Origem do cliente invalida")
    replace_person_companies(db, source, person_external_id, payload.company_ids)
    db.commit()
    return company_ids_for_person(db, source, person_external_id)


@app.delete("/customers/{customer_id}", tags=["Clientes"])
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    item = db.get(CustomerLink, customer_id)
    if not item or item.source != "local":
        raise HTTPException(status_code=404, detail="Cliente local nao encontrado")
    linked_order = db.scalar(
        select(SalesOrder).where(SalesOrder.customer_source == "local", SalesOrder.customer_external_id == str(customer_id))
    )
    if linked_order:
        raise HTTPException(status_code=400, detail="Cliente vinculado a pedidos")
    db.delete(item)
    db.commit()
    return {"ok": True}


@app.get("/customer-profiles", response_model=list[CustomerProfileRead], tags=["Perfis comerciais"])
def list_customer_profiles(db: Session = Depends(get_db)):
    items = db.scalars(select(CustomerProfile).order_by(CustomerProfile.code.asc(), CustomerProfile.name.asc())).all()
    return [customer_profile_to_read(db, item) for item in items]


@app.post("/customer-profiles", response_model=CustomerProfileRead, status_code=status.HTTP_201_CREATED, tags=["Perfis comerciais"])
def create_customer_profile(payload: CustomerProfileCreate, db: Session = Depends(get_db)):
    code = normalize_code(payload.code)
    exists = db.scalar(select(CustomerProfile).where(CustomerProfile.code == code))
    if exists:
        raise HTTPException(status_code=400, detail="Codigo do perfil comercial ja cadastrado")
    item = CustomerProfile(
        code=code,
        name=payload.name.strip(),
        description=payload.description,
        max_inactive_days=payload.max_inactive_days,
        max_overdue_days=payload.max_overdue_days,
        block_without_movement=payload.block_without_movement,
        block_overdue_titles=payload.block_overdue_titles,
        active=payload.active,
    )
    db.add(item)
    db.flush()
    replace_profile_payment_rules(db, item, payload.payment_rules)
    db.commit()
    db.refresh(item)
    return customer_profile_to_read(db, item)


@app.put("/customer-profiles/{profile_id}", response_model=CustomerProfileRead, tags=["Perfis comerciais"])
def update_customer_profile(profile_id: int, payload: CustomerProfileUpdate, db: Session = Depends(get_db)):
    item = get_profile_or_404(db, profile_id)
    code = normalize_code(payload.code)
    exists = db.scalar(select(CustomerProfile).where(CustomerProfile.code == code, CustomerProfile.id != profile_id))
    if exists:
        raise HTTPException(status_code=400, detail="Codigo do perfil comercial ja cadastrado")
    item.code = code
    item.name = payload.name.strip()
    item.description = payload.description
    item.max_inactive_days = payload.max_inactive_days
    item.max_overdue_days = payload.max_overdue_days
    item.block_without_movement = payload.block_without_movement
    item.block_overdue_titles = payload.block_overdue_titles
    item.active = payload.active
    replace_profile_payment_rules(db, item, payload.payment_rules)
    db.commit()
    db.refresh(item)
    return customer_profile_to_read(db, item)


@app.delete("/customer-profiles/{profile_id}", tags=["Perfis comerciais"])
def delete_customer_profile(profile_id: int, db: Session = Depends(get_db)):
    item = get_profile_or_404(db, profile_id)
    linked = db.scalar(select(CustomerLink).where(CustomerLink.customer_profile_id == profile_id))
    if linked:
        raise HTTPException(status_code=400, detail="Perfil comercial vinculado a clientes")
    db.delete(item)
    db.commit()
    return {"ok": True}


@app.put("/customers/{source}/{external_id}/profile", response_model=CustomerRead, tags=["Clientes"])
def assign_customer_profile(source: str, external_id: str, payload: CustomerProfileAssign, request: Request, db: Session = Depends(get_db)):
    get_profile_or_404(db, payload.customer_profile_id)
    if source == "local":
        link = db.get(CustomerLink, int(external_id)) if external_id.isdigit() else None
        if not link or link.source != "local":
            raise HTTPException(status_code=404, detail="Cliente local nao encontrado")
    elif source == "easyfinance":
        row = db.execute(
            text(
                """
                SELECT id, name, document_number, email, phone, city, state_code, active, credit_limit
                FROM people
                WHERE id = :id AND is_customer = TRUE
                """
            ),
            {"id": external_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Cliente EasyFinance nao encontrado")
        link = customer_link_for(db, "easyfinance", external_id)
        if not link:
            link = CustomerLink(source="easyfinance", external_id=external_id, name=row["name"], active=True)
            db.add(link)
    else:
        raise HTTPException(status_code=400, detail="Origem do cliente invalida")
    link.customer_profile_id = payload.customer_profile_id
    db.commit()
    db.refresh(link)
    return next(row for row in list_customers(request, db) if row["id"] == f"{source}:{external_id}")


@app.get("/customer-monitoring", response_model=list[CustomerMonitoringRead], tags=["Clientes"])
def customer_monitoring(request: Request, db: Session = Depends(get_db)):
    rows = []
    for customer in list_customers(request, db):
        source, _, external_id = customer["id"].partition(":")
        rows.append(
            customer_monitoring_row(
                db,
                customer["id"],
                source,
                external_id,
                customer["name"],
                customer["customer_profile_id"],
            )
        )
    rows.sort(key=lambda item: {"critical": 0, "attention": 1, "healthy": 2}[item["health_status"]])
    return rows


@app.post("/customer-monitoring/{source}/{external_id}/apply-suggested-profile", response_model=CustomerRead, tags=["Clientes"])
def apply_suggested_customer_profile(source: str, external_id: str, request: Request, db: Session = Depends(get_db)):
    customer_id = f"{source}:{external_id}"
    customer = next((row for row in list_customers(request, db) if row["id"] == customer_id), None)
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")
    suggestion = customer_monitoring_row(
        db,
        customer_id,
        source,
        external_id,
        customer["name"],
        customer["customer_profile_id"],
    )
    if not suggestion["suggested_profile_id"]:
        raise HTTPException(status_code=400, detail="Cliente sem perfil sugerido")
    return assign_customer_profile(
        source,
        external_id,
        CustomerProfileAssign(customer_profile_id=suggestion["suggested_profile_id"]),
        request,
        db,
    )


@app.get("/product-groups", response_model=list[ProductGroupRead], tags=["Produtos"])
def list_product_groups(request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    items = db.scalars(
        select(ProductGroup)
        .where(text("EXISTS (SELECT 1 FROM control_catalog_companies cc WHERE cc.company_id = :company_id AND cc.catalog_key = 'sf_product_groups' AND cc.record_id = CAST(sf_product_groups.id AS VARCHAR) AND cc.active = TRUE)"))
        .params(company_id=company_id)
        .order_by(ProductGroup.code.asc(), ProductGroup.name.asc())
    ).all()
    return [group_to_read(db, item) for item in items]


@app.post("/product-groups", response_model=ProductGroupRead, status_code=status.HTTP_201_CREATED, tags=["Produtos"])
def create_product_group(payload: ProductGroupCreate, request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    code = normalize_code(payload.code)
    exists = db.scalar(select(ProductGroup).where(ProductGroup.code == code))
    if exists:
        raise HTTPException(status_code=400, detail="Codigo do grupo de produto ja cadastrado")
    item = ProductGroup(code=code, name=payload.name.strip(), description=payload.description, active=payload.active)
    db.add(item)
    db.flush()
    ensure_catalog_company(db, company_id, "sf_product_groups", item.id)
    db.commit()
    db.refresh(item)
    return group_to_read(db, item)


@app.put("/product-groups/{group_id}", response_model=ProductGroupRead, tags=["Produtos"])
def update_product_group(group_id: int, payload: ProductGroupUpdate, db: Session = Depends(get_db)):
    item = db.get(ProductGroup, group_id)
    if not item:
        raise HTTPException(status_code=404, detail="Grupo de produto nao encontrado")
    code = normalize_code(payload.code)
    exists = db.scalar(select(ProductGroup).where(ProductGroup.code == code, ProductGroup.id != group_id))
    if exists:
        raise HTTPException(status_code=400, detail="Codigo do grupo de produto ja cadastrado")
    item.code = code
    item.name = payload.name.strip()
    item.description = payload.description
    item.active = payload.active
    db.commit()
    db.refresh(item)
    return group_to_read(db, item)


@app.put("/product-groups/{group_id}/companies", response_model=ProductGroupRead, tags=["Produtos"])
def update_product_group_companies(group_id: int, payload: CompanyLinkUpdate, db: Session = Depends(get_db)):
    item = db.get(ProductGroup, group_id)
    if not item:
        raise HTTPException(status_code=404, detail="Grupo de produto nao encontrado")
    replace_catalog_companies(db, "sf_product_groups", item.id, payload.company_ids)
    db.commit()
    db.refresh(item)
    return group_to_read(db, item)


@app.delete("/product-groups/{group_id}", tags=["Produtos"])
def delete_product_group(group_id: int, db: Session = Depends(get_db)):
    item = db.get(ProductGroup, group_id)
    if not item:
        raise HTTPException(status_code=404, detail="Grupo de produto nao encontrado")
    linked = db.scalar(select(ProductClass).where(ProductClass.product_group_id == group_id)) or db.scalar(
        select(Product).where(Product.product_group_id == group_id)
    )
    if linked:
        raise HTTPException(status_code=400, detail="Grupo vinculado a classes ou produtos")
    db.delete(item)
    db.commit()
    return {"ok": True}


@app.get("/product-classes", response_model=list[ProductClassRead], tags=["Produtos"])
def list_product_classes(request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    items = db.scalars(
        select(ProductClass)
        .where(text("EXISTS (SELECT 1 FROM control_catalog_companies cc WHERE cc.company_id = :company_id AND cc.catalog_key = 'sf_product_classes' AND cc.record_id = CAST(sf_product_classes.id AS VARCHAR) AND cc.active = TRUE)"))
        .params(company_id=company_id)
        .order_by(ProductClass.code.asc(), ProductClass.name.asc())
    ).all()
    return [class_to_read(db, item) for item in items]


@app.post("/product-classes", response_model=ProductClassRead, status_code=status.HTTP_201_CREATED, tags=["Produtos"])
def create_product_class(payload: ProductClassCreate, request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    code = normalize_code(payload.code)
    exists = db.scalar(select(ProductClass).where(ProductClass.code == code))
    if exists:
        raise HTTPException(status_code=400, detail="Codigo da classe de produto ja cadastrado")
    get_group_or_404(db, payload.product_group_id)
    if payload.product_group_id and not catalog_available_for_company(db, company_id, "sf_product_groups", payload.product_group_id):
        raise HTTPException(status_code=400, detail="Grupo nao liberado para a empresa ativa")
    item = ProductClass(
        product_group_id=payload.product_group_id,
        code=code,
        name=payload.name.strip(),
        description=payload.description,
        active=payload.active,
    )
    db.add(item)
    db.flush()
    ensure_catalog_company(db, company_id, "sf_product_classes", item.id)
    db.commit()
    db.refresh(item)
    return class_to_read(db, item)


@app.put("/product-classes/{class_id}", response_model=ProductClassRead, tags=["Produtos"])
def update_product_class(class_id: int, payload: ProductClassUpdate, request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    item = db.get(ProductClass, class_id)
    if not item:
        raise HTTPException(status_code=404, detail="Classe de produto nao encontrada")
    code = normalize_code(payload.code)
    exists = db.scalar(select(ProductClass).where(ProductClass.code == code, ProductClass.id != class_id))
    if exists:
        raise HTTPException(status_code=400, detail="Codigo da classe de produto ja cadastrado")
    get_group_or_404(db, payload.product_group_id)
    if payload.product_group_id and not catalog_available_for_company(db, company_id, "sf_product_groups", payload.product_group_id):
        raise HTTPException(status_code=400, detail="Grupo nao liberado para a empresa ativa")
    item.product_group_id = payload.product_group_id
    item.code = code
    item.name = payload.name.strip()
    item.description = payload.description
    item.active = payload.active
    db.commit()
    db.refresh(item)
    return class_to_read(db, item)


@app.put("/product-classes/{class_id}/companies", response_model=ProductClassRead, tags=["Produtos"])
def update_product_class_companies(class_id: int, payload: CompanyLinkUpdate, db: Session = Depends(get_db)):
    item = db.get(ProductClass, class_id)
    if not item:
        raise HTTPException(status_code=404, detail="Classe de produto nao encontrada")
    replace_catalog_companies(db, "sf_product_classes", item.id, payload.company_ids)
    db.commit()
    db.refresh(item)
    return class_to_read(db, item)


@app.delete("/product-classes/{class_id}", tags=["Produtos"])
def delete_product_class(class_id: int, db: Session = Depends(get_db)):
    item = db.get(ProductClass, class_id)
    if not item:
        raise HTTPException(status_code=404, detail="Classe de produto nao encontrada")
    linked = db.scalar(select(Product).where(Product.product_class_id == class_id))
    if linked:
        raise HTTPException(status_code=400, detail="Classe vinculada a produtos")
    db.delete(item)
    db.commit()
    return {"ok": True}


@app.get("/products", response_model=list[ProductRead], tags=["Produtos"])
def list_products(request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    items = db.scalars(
        select(Product)
        .where(text("EXISTS (SELECT 1 FROM control_product_companies pc WHERE pc.company_id = :company_id AND pc.product_source = 'easysales' AND pc.product_external_id = CAST(sf_products.id AS VARCHAR) AND pc.active = TRUE)"))
        .params(company_id=company_id)
        .order_by(Product.sku.asc(), Product.name.asc())
    ).all()
    return [product_to_read(db, item) for item in items]


@app.put("/products/{product_id}/companies", response_model=ProductRead, tags=["Produtos"])
def update_product_companies(product_id: int, payload: CompanyLinkUpdate, db: Session = Depends(get_db)):
    item = db.get(Product, product_id)
    if not item:
        raise HTTPException(status_code=404, detail="Produto nao encontrado")
    replace_product_companies(db, item.id, payload.company_ids, item.default_warehouse_id)
    db.commit()
    db.refresh(item)
    return product_to_read(db, item)


@app.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED, tags=["Produtos"])
def create_product(payload: ProductCreate, request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    sku = normalize_code(payload.sku, "SKU")
    exists = db.scalar(select(Product).where(Product.sku == sku))
    if exists:
        raise HTTPException(status_code=400, detail="SKU ja cadastrado")
    if Decimal(str(payload.sale_price)) < 0:
        raise HTTPException(status_code=400, detail="Preco de venda nao pode ser negativo")
    if Decimal(str(payload.purchase_price)) < 0 or Decimal(str(payload.cost_price)) < 0:
        raise HTTPException(status_code=400, detail="Preco de compra e custo nao podem ser negativos")
    get_group_or_404(db, payload.product_group_id)
    get_class_or_404(db, payload.product_class_id)
    warehouse = resolve_warehouse(db, payload.default_warehouse_id)
    item = Product(
        product_group_id=payload.product_group_id,
        product_class_id=payload.product_class_id,
        sku=sku,
        name=payload.name.strip(),
        unit=payload.unit.strip().upper() or "UN",
        purchase_price=payload.purchase_price,
        cost_price=payload.cost_price,
        sale_price=payload.sale_price,
        default_warehouse_id=warehouse["id"] if warehouse else None,
        default_warehouse_name=warehouse["name"] if warehouse else None,
        description=payload.description,
        active=payload.active,
    )
    db.add(item)
    db.flush()
    ensure_product_company(db, company_id, item.id, warehouse["id"] if warehouse else None)
    db.commit()
    db.refresh(item)
    return product_to_read(db, item)


@app.put("/products/{product_id}", response_model=ProductRead, tags=["Produtos"])
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)):
    item = db.get(Product, product_id)
    if not item:
        raise HTTPException(status_code=404, detail="Produto nao encontrado")
    sku = normalize_code(payload.sku, "SKU")
    exists = db.scalar(select(Product).where(Product.sku == sku, Product.id != product_id))
    if exists:
        raise HTTPException(status_code=400, detail="SKU ja cadastrado")
    if Decimal(str(payload.sale_price)) < 0:
        raise HTTPException(status_code=400, detail="Preco de venda nao pode ser negativo")
    if Decimal(str(payload.purchase_price)) < 0 or Decimal(str(payload.cost_price)) < 0:
        raise HTTPException(status_code=400, detail="Preco de compra e custo nao podem ser negativos")
    get_group_or_404(db, payload.product_group_id)
    get_class_or_404(db, payload.product_class_id)
    warehouse = resolve_warehouse(db, payload.default_warehouse_id)
    item.product_group_id = payload.product_group_id
    item.product_class_id = payload.product_class_id
    item.sku = sku
    item.name = payload.name.strip()
    item.unit = payload.unit.strip().upper() or "UN"
    item.purchase_price = payload.purchase_price
    item.cost_price = payload.cost_price
    item.sale_price = payload.sale_price
    item.default_warehouse_id = warehouse["id"] if warehouse else None
    item.default_warehouse_name = warehouse["name"] if warehouse else None
    item.description = payload.description
    item.active = payload.active
    db.commit()
    db.refresh(item)
    return product_to_read(db, item)


@app.delete("/products/{product_id}", tags=["Produtos"])
def delete_product(product_id: int, db: Session = Depends(get_db)):
    item = db.get(Product, product_id)
    if not item:
        raise HTTPException(status_code=404, detail="Produto nao encontrado")
    linked_price_table = db.scalar(select(PriceTableItem).where(PriceTableItem.product_id == product_id))
    if linked_price_table:
        raise HTTPException(status_code=400, detail="Produto vinculado a tabela de preco. Remova o item da tabela antes de excluir o produto.")
    linked_order = db.scalar(select(SalesOrderItem).where(SalesOrderItem.product_id == product_id))
    if linked_order:
        raise HTTPException(status_code=400, detail="Produto vinculado a pedidos. Inative o produto para impedir novas vendas.")
    db.delete(item)
    db.commit()
    return {"ok": True}


@app.put("/products/{product_id}/lot-config", response_model=ProductRead, tags=["Produtos"])
def update_product_lot_config(product_id: int, payload: ProductLotConfigUpdate, db: Session = Depends(get_db)):
    item = db.get(Product, product_id)
    if not item:
        raise HTTPException(status_code=404, detail="Produto nao encontrado")
    lot_type = payload.lot_type if payload.controls_lot else "none"
    existing = db.execute(
        text(
            """
            SELECT id
            FROM flow_product_lot_configs
            WHERE product_source = 'easysales' AND product_external_id = :product_id
            """
        ),
        {"product_id": str(product_id)},
    ).mappings().first()
    if existing:
        db.execute(
            text(
                """
                UPDATE flow_product_lot_configs
                SET controls_lot = :controls_lot, lot_type = :lot_type, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """
            ),
            {"id": existing["id"], "controls_lot": payload.controls_lot, "lot_type": lot_type},
        )
    else:
        db.execute(
            text(
                """
                INSERT INTO flow_product_lot_configs (product_source, product_external_id, controls_lot, lot_type, updated_at)
                VALUES ('easysales', :product_id, :controls_lot, :lot_type, CURRENT_TIMESTAMP)
                """
            ),
            {"product_id": str(product_id), "controls_lot": payload.controls_lot, "lot_type": lot_type},
        )
    db.commit()
    db.refresh(item)
    return product_to_read(db, item)


@app.get("/stock-balances", response_model=list[StockBalanceRead], tags=["Produtos"])
def list_stock_balances(request: Request, product_external_id: str | None = None, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    try:
        rows = db.execute(
            text(
                """
                SELECT
                    bl.warehouse_id,
                    w.name AS warehouse_name,
                    bl.balance_type_id,
                    bl.balance_code,
                    bl.balance_name,
                    bl.product_source,
                    bl.product_external_id,
                    bl.product_sku,
                    bl.product_name,
                    COALESCE(SUM(bl.quantity), 0) AS balance_quantity
                FROM flow_balance_ledger bl
                JOIN flow_warehouses w ON w.id = bl.warehouse_id
                WHERE bl.company_id = :company_id
                  AND (:product_external_id IS NULL OR bl.product_external_id = :product_external_id)
                GROUP BY
                    bl.warehouse_id, w.name, bl.balance_type_id, bl.balance_code, bl.balance_name,
                    bl.product_source, bl.product_external_id, bl.product_sku, bl.product_name
                ORDER BY w.name ASC, bl.balance_code ASC, bl.product_sku ASC
                """
            ),
            {"product_external_id": product_external_id, "company_id": company_id},
        ).mappings().all()
        return rows
    except SQLAlchemyError:
        db.rollback()
        return []


@app.get("/stock-movements", response_model=list[StockMovementRead], tags=["Produtos"])
def list_stock_movements(request: Request, product_external_id: str | None = None, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    try:
        rows = db.execute(
            text(
                """
                SELECT
                    m.id,
                    m.warehouse_id,
                    w.name AS warehouse_name,
                    COALESCE(d.operation_code, m.operation_code) AS operation_code,
                    ot.name AS operation_name,
                    COALESCE(d.document_type_code, m.document_type_code) AS document_type_code,
                    COALESCE(d.document_number, m.document_number) AS document_number,
                    COALESCE(d.document_series, m.document_series) AS document_series,
                    COALESCE(d.issue_date, m.issue_date) AS issue_date,
                    COALESCE(d.movement_date, m.movement_date) AS movement_date,
                    m.product_source,
                    m.product_external_id,
                    p.sku AS product_sku,
                    p.name AS product_name,
                    m.movement_type,
                    m.quantity,
                    m.unit_price,
                    m.created_at
                FROM flow_stock_movements m
                LEFT JOIN flow_movement_documents d ON d.id = m.movement_document_id
                LEFT JOIN flow_operation_types ot ON ot.id = COALESCE(d.operation_type_id, m.operation_type_id)
                LEFT JOIN sf_products p ON CAST(p.id AS VARCHAR) = m.product_external_id
                JOIN flow_warehouses w ON w.id = m.warehouse_id
                WHERE COALESCE(d.company_id, m.company_id) = :company_id
                  AND (:product_external_id IS NULL OR m.product_external_id = :product_external_id)
                ORDER BY m.id DESC
                """
            ),
            {"product_external_id": product_external_id, "company_id": company_id},
        ).mappings().all()
        return rows
    except SQLAlchemyError:
        db.rollback()
        return []


@app.get("/price-tables", response_model=list[PriceTableRead], tags=["Tabelas de preco"])
def list_price_tables(request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    items = db.scalars(
        select(PriceTable)
        .where(text("EXISTS (SELECT 1 FROM control_catalog_companies cc WHERE cc.company_id = :company_id AND cc.catalog_key = 'sf_price_tables' AND cc.record_id = CAST(sf_price_tables.id AS VARCHAR) AND cc.active = TRUE)"))
        .params(company_id=company_id)
        .order_by(PriceTable.code.asc(), PriceTable.name.asc())
    ).all()
    return [price_table_to_read(db, item) for item in items]


@app.post("/price-tables", response_model=PriceTableRead, status_code=status.HTTP_201_CREATED, tags=["Tabelas de preco"])
def create_price_table(payload: PriceTableCreate, request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    code = normalize_code(payload.code)
    exists = db.scalar(select(PriceTable).where(PriceTable.code == code))
    if exists:
        raise HTTPException(status_code=400, detail="Codigo da tabela de preco ja cadastrado")
    item = PriceTable(
        code=code,
        name=payload.name.strip(),
        correction_mode=normalize_correction_mode(payload.correction_mode),
        monthly_rate=payload.monthly_rate,
        base_date=payload.base_date,
        active=payload.active,
    )
    db.add(item)
    db.flush()
    ensure_catalog_company(db, company_id, "sf_price_tables", item.id)
    db.commit()
    db.refresh(item)
    return price_table_to_read(db, item)


@app.put("/price-tables/{price_table_id}", response_model=PriceTableRead, tags=["Tabelas de preco"])
def update_price_table(price_table_id: int, payload: PriceTableUpdate, db: Session = Depends(get_db)):
    item = get_price_table_or_404(db, price_table_id)
    code = normalize_code(payload.code)
    exists = db.scalar(select(PriceTable).where(PriceTable.code == code, PriceTable.id != price_table_id))
    if exists:
        raise HTTPException(status_code=400, detail="Codigo da tabela de preco ja cadastrado")
    item.code = code
    item.name = payload.name.strip()
    item.correction_mode = normalize_correction_mode(payload.correction_mode)
    item.monthly_rate = payload.monthly_rate
    item.base_date = payload.base_date
    item.active = payload.active
    db.commit()
    db.refresh(item)
    return price_table_to_read(db, item)


@app.put("/price-tables/{price_table_id}/companies", response_model=PriceTableRead, tags=["Tabelas de preco"])
def update_price_table_companies(price_table_id: int, payload: CompanyLinkUpdate, db: Session = Depends(get_db)):
    item = get_price_table_or_404(db, price_table_id)
    replace_catalog_companies(db, "sf_price_tables", item.id, payload.company_ids)
    db.commit()
    db.refresh(item)
    return price_table_to_read(db, item)


@app.delete("/price-tables/{price_table_id}", tags=["Tabelas de preco"])
def delete_price_table(price_table_id: int, db: Session = Depends(get_db)):
    item = get_price_table_or_404(db, price_table_id)
    linked_order = db.scalar(select(SalesOrder).where(SalesOrder.price_table_id == price_table_id))
    if linked_order:
        raise HTTPException(status_code=400, detail="Tabela vinculada a pedidos")
    for table_item in db.scalars(select(PriceTableItem).where(PriceTableItem.price_table_id == price_table_id)).all():
        for tier in db.scalars(select(PriceTableItemTier).where(PriceTableItemTier.price_table_item_id == table_item.id)).all():
            db.delete(tier)
        db.delete(table_item)
    db.delete(item)
    db.commit()
    return {"ok": True}


@app.get("/price-tables/{price_table_id}/items", response_model=list[PriceTableItemRead], tags=["Tabelas de preco"])
def list_price_table_items(price_table_id: int, db: Session = Depends(get_db)):
    get_price_table_or_404(db, price_table_id)
    items = db.scalars(
        select(PriceTableItem).where(PriceTableItem.price_table_id == price_table_id).order_by(PriceTableItem.id.asc())
    ).all()
    return [price_table_item_to_read(db, item) for item in items]


@app.post("/price-tables/{price_table_id}/items", response_model=PriceTableItemRead, status_code=status.HTTP_201_CREATED, tags=["Tabelas de preco"])
def create_price_table_item(price_table_id: int, payload: PriceTableItemCreate, db: Session = Depends(get_db)):
    get_price_table_or_404(db, price_table_id)
    product = db.get(Product, payload.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Produto nao encontrado")
    exists = db.scalar(
        select(PriceTableItem).where(PriceTableItem.price_table_id == price_table_id, PriceTableItem.product_id == payload.product_id)
    )
    if exists:
        raise HTTPException(status_code=400, detail="Produto ja cadastrado nesta tabela")
    if Decimal(str(payload.base_price)) < 0:
        raise HTTPException(status_code=400, detail="Preco base nao pode ser negativo")
    if Decimal(str(payload.margin_percent)) < 0:
        raise HTTPException(status_code=400, detail="Margem nao pode ser negativa")
    item = PriceTableItem(
        price_table_id=price_table_id,
        product_id=payload.product_id,
        base_price=payload.base_price,
        margin_percent=payload.margin_percent,
        active=payload.active,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return price_table_item_to_read(db, item)


@app.put("/price-table-items/{item_id}", response_model=PriceTableItemRead, tags=["Tabelas de preco"])
def update_price_table_item(item_id: int, payload: PriceTableItemUpdate, db: Session = Depends(get_db)):
    item = db.get(PriceTableItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item da tabela de preco nao encontrado")
    product = db.get(Product, payload.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Produto nao encontrado")
    exists = db.scalar(
        select(PriceTableItem).where(
            PriceTableItem.price_table_id == item.price_table_id,
            PriceTableItem.product_id == payload.product_id,
            PriceTableItem.id != item_id,
        )
    )
    if exists:
        raise HTTPException(status_code=400, detail="Produto ja cadastrado nesta tabela")
    if Decimal(str(payload.base_price)) < 0:
        raise HTTPException(status_code=400, detail="Preco base nao pode ser negativo")
    if Decimal(str(payload.margin_percent)) < 0:
        raise HTTPException(status_code=400, detail="Margem nao pode ser negativa")
    item.product_id = payload.product_id
    item.base_price = payload.base_price
    item.margin_percent = payload.margin_percent
    item.active = payload.active
    db.commit()
    db.refresh(item)
    return price_table_item_to_read(db, item)


@app.delete("/price-table-items/{item_id}", tags=["Tabelas de preco"])
def delete_price_table_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(PriceTableItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item da tabela de preco nao encontrado")
    for tier in db.scalars(select(PriceTableItemTier).where(PriceTableItemTier.price_table_item_id == item_id)).all():
        db.delete(tier)
    db.delete(item)
    db.commit()
    return {"ok": True}


@app.get("/price-table-items/{item_id}/tiers", response_model=list[PriceTableItemTierRead], tags=["Tabelas de preco"])
def list_price_table_item_tiers(item_id: int, db: Session = Depends(get_db)):
    item = db.get(PriceTableItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item da tabela de preco nao encontrado")
    return db.scalars(
        select(PriceTableItemTier)
        .where(PriceTableItemTier.price_table_item_id == item_id)
        .order_by(PriceTableItemTier.min_quantity.asc())
    ).all()


@app.post("/price-table-items/{item_id}/tiers", response_model=PriceTableItemTierRead, status_code=status.HTTP_201_CREATED, tags=["Tabelas de preco"])
def create_price_table_item_tier(item_id: int, payload: PriceTableItemTierCreate, db: Session = Depends(get_db)):
    item = db.get(PriceTableItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item da tabela de preco nao encontrado")
    if Decimal(str(payload.min_quantity)) <= 0:
        raise HTTPException(status_code=400, detail="Quantidade minima deve ser maior que zero")
    if Decimal(str(payload.discount_percent)) < 0 or Decimal(str(payload.discount_percent)) >= 100:
        raise HTTPException(status_code=400, detail="Desconto deve ficar entre 0 e 99,9999")
    exists = db.scalar(
        select(PriceTableItemTier).where(
            PriceTableItemTier.price_table_item_id == item_id,
            PriceTableItemTier.min_quantity == payload.min_quantity,
        )
    )
    if exists:
        raise HTTPException(status_code=400, detail="Ja existe faixa para esta quantidade minima")
    tier = PriceTableItemTier(
        price_table_item_id=item_id,
        min_quantity=payload.min_quantity,
        discount_percent=payload.discount_percent,
        active=payload.active,
    )
    db.add(tier)
    db.commit()
    db.refresh(tier)
    return tier


@app.put("/price-table-item-tiers/{tier_id}", response_model=PriceTableItemTierRead, tags=["Tabelas de preco"])
def update_price_table_item_tier(tier_id: int, payload: PriceTableItemTierUpdate, db: Session = Depends(get_db)):
    tier = db.get(PriceTableItemTier, tier_id)
    if not tier:
        raise HTTPException(status_code=404, detail="Faixa progressiva nao encontrada")
    if Decimal(str(payload.min_quantity)) <= 0:
        raise HTTPException(status_code=400, detail="Quantidade minima deve ser maior que zero")
    if Decimal(str(payload.discount_percent)) < 0 or Decimal(str(payload.discount_percent)) >= 100:
        raise HTTPException(status_code=400, detail="Desconto deve ficar entre 0 e 99,9999")
    exists = db.scalar(
        select(PriceTableItemTier).where(
            PriceTableItemTier.price_table_item_id == tier.price_table_item_id,
            PriceTableItemTier.min_quantity == payload.min_quantity,
            PriceTableItemTier.id != tier_id,
        )
    )
    if exists:
        raise HTTPException(status_code=400, detail="Ja existe faixa para esta quantidade minima")
    tier.min_quantity = payload.min_quantity
    tier.discount_percent = payload.discount_percent
    tier.active = payload.active
    db.commit()
    db.refresh(tier)
    return tier


@app.delete("/price-table-item-tiers/{tier_id}", tags=["Tabelas de preco"])
def delete_price_table_item_tier(tier_id: int, db: Session = Depends(get_db)):
    tier = db.get(PriceTableItemTier, tier_id)
    if not tier:
        raise HTTPException(status_code=404, detail="Faixa progressiva nao encontrada")
    db.delete(tier)
    db.commit()
    return {"ok": True}


@app.get("/price-preview", response_model=PricePreviewRead, tags=["Tabelas de preco"])
def price_preview(price_table_id: int, product_id: int, payment_due_date: date, quantity: Decimal = Decimal("1"), db: Session = Depends(get_db)):
    table = get_price_table_or_404(db, price_table_id)
    item = db.scalar(
        select(PriceTableItem).where(
            PriceTableItem.price_table_id == price_table_id,
            PriceTableItem.product_id == product_id,
            PriceTableItem.active == True,
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="Produto sem preco ativo na tabela")
    days = max((payment_due_date - table.base_date).days, 0)
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantidade deve ser maior que zero")
    factor = correction_factor(table, payment_due_date)
    price_before_discount = money_round(Decimal(str(item.base_price)) * factor)
    tier = applicable_progressive_tier(db, item, quantity)
    return {
        "price_table_id": price_table_id,
        "product_id": product_id,
        "base_price": item.base_price,
        "corrected_price": apply_progressive_discount(price_before_discount, tier),
        "correction_mode": table.correction_mode,
        "correction_factor": factor,
        "days": days,
        "quantity": quantity,
        "progressive_discount_percent": tier.discount_percent if tier else Decimal("0"),
        "progressive_tier_min_quantity": tier.min_quantity if tier else None,
        "price_before_progressive_discount": price_before_discount,
    }


@app.get("/orders", response_model=list[SalesOrderRead], tags=["Pedidos"])
def list_orders(request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    orders = db.scalars(select(SalesOrder).where(SalesOrder.company_id == company_id).order_by(SalesOrder.id.desc())).all()
    return [order_to_read(db, order) for order in orders]


@app.get("/orders/{order_id}", response_model=SalesOrderRead, tags=["Pedidos"])
def get_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    return order_to_read(db, order)


@app.post("/orders", response_model=SalesOrderRead, status_code=status.HTTP_201_CREATED, tags=["Pedidos"])
def create_order(payload: SalesOrderCreate, request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    table = get_price_table_or_404(db, payload.price_table_id)
    if not table.active:
        raise HTTPException(status_code=400, detail="Tabela de preco inativa")
    customer = resolve_customer(db, payload.customer_id)
    if not person_available_for_company(db, company_id, customer["source"], customer["external_id"]):
        raise HTTPException(status_code=400, detail="Cliente nao vinculado a empresa ativa")
    order = SalesOrder(
        company_id=company_id,
        order_number=next_order_number(db),
        order_type=normalize_order_type(payload.order_type),
        customer_source=customer["source"],
        customer_external_id=customer["external_id"],
        customer_name=customer["name"],
        price_table_id=table.id,
        order_date=payload.order_date,
        payment_due_date=payload.payment_due_date,
        delivery_date=payload.delivery_date,
        status="draft",
        approval_stage="draft",
        total_amount=Decimal("0"),
        total_cost_amount=Decimal("0"),
        gross_profit_amount=Decimal("0"),
        profitability_percent=Decimal("0"),
        notes=payload.notes,
    )
    db.add(order)
    db.flush()
    sales_order_operation(db, order)
    build_order_items(db, order, table, payload.items, payload.payment_due_date)
    recalculate_order_totals(db, order)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.post("/orders/{order_id}/items", response_model=SalesOrderRead, status_code=status.HTTP_201_CREATED, tags=["Pedidos"])
def create_order_item(order_id: int, payload: SalesOrderItemCreate, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    was_submitted = order.approval_stage != "draft"
    table = get_price_table_or_404(db, order.price_table_id)
    build_order_items(db, order, table, [payload], order.payment_due_date)
    recalculate_order_totals(db, order)
    revalidate_order_if_submitted(db, order, was_submitted)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.put("/orders/{order_id}/items/{item_id}", response_model=SalesOrderRead, tags=["Pedidos"])
def update_order_item(order_id: int, item_id: int, payload: SalesOrderItemCreate, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    item = db.get(SalesOrderItem, item_id)
    if not item or item.order_id != order.id:
        raise HTTPException(status_code=404, detail="Item do pedido nao encontrado")
    was_submitted = order.approval_stage != "draft"
    table = get_price_table_or_404(db, order.price_table_id)
    apply_payload_to_order_item(db, order, table, payload, item=item)
    recalculate_order_totals(db, order)
    revalidate_order_if_submitted(db, order, was_submitted)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.delete("/orders/{order_id}/items/{item_id}", response_model=SalesOrderRead, tags=["Pedidos"])
def delete_order_item(order_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    item = db.get(SalesOrderItem, item_id)
    if not item or item.order_id != order.id:
        raise HTTPException(status_code=404, detail="Item do pedido nao encontrado")
    was_submitted = order.approval_stage != "draft"
    ensure_order_item_has_editable_balance(db, item, deleting=True)
    db.delete(item)
    db.flush()
    recalculate_order_totals(db, order)
    revalidate_order_if_submitted(db, order, was_submitted)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.put("/orders/{order_id}", response_model=SalesOrderRead, tags=["Pedidos"])
def update_order(order_id: int, payload: SalesOrderUpdate, request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    order = order_for_company_or_404(db, order_id, company_id)
    was_submitted = order.approval_stage != "draft"
    table = get_price_table_or_404(db, payload.price_table_id)
    if not table.active:
        raise HTTPException(status_code=400, detail="Tabela de preco inativa")
    customer = resolve_customer(db, payload.customer_id)
    if not person_available_for_company(db, company_id, customer["source"], customer["external_id"]):
        raise HTTPException(status_code=400, detail="Cliente nao vinculado a empresa ativa")
    existing_items = db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id).order_by(SalesOrderItem.id.asc())).all()
    has_linked_items = any(linked_quantity_for_order_item(db, item.id) > 0 for item in existing_items)
    order.customer_source = customer["source"]
    order.order_type = normalize_order_type(payload.order_type)
    order.customer_external_id = customer["external_id"]
    order.customer_name = customer["name"]
    order.price_table_id = table.id
    order.order_date = payload.order_date
    order.payment_due_date = payload.payment_due_date
    order.delivery_date = payload.delivery_date
    if not was_submitted:
        order.status = "draft"
        order.approval_stage = "draft"
        order.approval_notes = None
        order.financial_approved_at = None
        order.commercial_approved_at = None
    order.notes = payload.notes
    if has_linked_items:
        if len(payload.items) < len(existing_items):
            raise HTTPException(status_code=400, detail="Pedido com baixa vinculada no Flow nao permite remover itens pelo cabecalho")
        for index, item in enumerate(existing_items):
            payload_item = payload.items[index] if index < len(payload.items) else None
            if not payload_item:
                continue
            if linked_quantity_for_order_item(db, item.id) > 0 and item.product_id != payload_item.product_id:
                raise HTTPException(status_code=400, detail="Item com baixa vinculada no Flow nao permite troca de produto")
            apply_payload_to_order_item(db, order, table, payload_item, item=item)
        for payload_item in payload.items[len(existing_items):]:
            apply_payload_to_order_item(db, order, table, payload_item)
    else:
        for item in existing_items:
            db.delete(item)
        db.flush()
        build_order_items(db, order, table, payload.items, payload.payment_due_date)
    recalculate_order_totals(db, order)
    revalidate_order_if_submitted(db, order, was_submitted)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.post("/orders/{order_id}/payment-suggestions/generate", response_model=SalesOrderRead, tags=["Pedidos"])
def generate_order_payment_suggestions(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    was_submitted = order.approval_stage != "draft"
    if Decimal(str(order.total_amount or 0)) <= 0:
        raise HTTPException(status_code=400, detail="Pedido sem total para gerar sugestao de pagamento")
    for item in db.scalars(select(SalesOrderPayment).where(SalesOrderPayment.order_id == order.id)).all():
        db.delete(item)
    db.add(
        SalesOrderPayment(
            company_id=order.company_id,
            order_id=order.id,
            payment_method="avista",
            due_date=order.payment_due_date,
            amount=order.total_amount,
            notes="Condicao comercial gerada pelo pedido.",
        )
    )
    if was_submitted:
        apply_order_approval_flow(db, order)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.put("/orders/{order_id}/payment-suggestions", response_model=SalesOrderRead, tags=["Pedidos"])
def save_order_payment_suggestions(order_id: int, payload: list[SalesOrderPaymentCreate], request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    was_submitted = order.approval_stage != "draft"
    validate_payment_suggestions(order, payload)
    for item in db.scalars(select(SalesOrderPayment).where(SalesOrderPayment.order_id == order.id)).all():
        db.delete(item)
    for item in payload:
        db.add(
            SalesOrderPayment(
                company_id=order.company_id,
                order_id=order.id,
                payment_method=item.payment_method,
                due_date=item.due_date,
                amount=item.amount,
                notes=item.notes,
            )
        )
    if was_submitted:
        apply_order_approval_flow(db, order)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.post("/orders/{order_id}/submit", response_model=SalesOrderRead, tags=["Pedidos"])
def submit_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    recalculate_order_totals(db, order)
    if Decimal(str(order.total_amount or 0)) <= 0:
        raise HTTPException(status_code=400, detail="Pedido sem itens ou total zerado")
    has_payment_suggestion = db.scalar(select(SalesOrderPayment).where(SalesOrderPayment.order_id == order.id))
    if not has_payment_suggestion:
        raise HTTPException(status_code=400, detail="Registre a condicao de pagamento antes de enviar para aprovacao.")
    apply_order_approval_flow(db, order)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.post("/orders/{order_id}/approve-financial", response_model=SalesOrderRead, tags=["Pedidos"])
def approve_order_financial(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    recalculate_order_totals(db, order)
    allowed, notes = evaluate_financial_approval(db, order)
    order.financial_approved_at = datetime.utcnow()
    if allowed:
        order.approval_notes = " ".join(notes)
    else:
        order.approval_notes = "Aprovacao financeira manual: " + " ".join(notes)
    pending_commercial = db.scalar(
        select(SalesOrderItem).where(
            SalesOrderItem.order_id == order.id,
            SalesOrderItem.commercial_status == "pending",
        )
    )
    if pending_commercial:
        order.status = "pending_commercial"
        order.approval_stage = "commercial"
    else:
        order.status = "approved"
        order.approval_stage = "approved"
        order.commercial_approved_at = datetime.utcnow()
        if allowed:
            order.approval_notes = "Pedido aprovado automaticamente na etapa comercial."
    sync_order_balance_ledger(db, order)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.post("/orders/{order_id}/approve-commercial", response_model=SalesOrderRead, tags=["Pedidos"])
def approve_order_commercial(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    if order.status not in {"pending_commercial", "financial_blocked"}:
        raise HTTPException(status_code=400, detail="Pedido precisa passar pela aprovacao financeira")
    pending = db.scalar(
        select(SalesOrderItem).where(
            SalesOrderItem.order_id == order.id,
            SalesOrderItem.commercial_status == "pending",
        )
    )
    if pending:
        raise HTTPException(status_code=400, detail="A aprovacao comercial agora deve ser feita item a item")
    refresh_order_approval_stage(db, order)
    sync_order_balance_ledger(db, order)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.post("/orders/{order_id}/items/{item_id}/approve-commercial", response_model=SalesOrderRead, tags=["Pedidos"])
def approve_order_item_commercial(order_id: int, item_id: int, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    item = db.get(SalesOrderItem, item_id)
    if not item or item.order_id != order.id:
        raise HTTPException(status_code=404, detail="Item do pedido nao encontrado")
    item.commercial_status = "approved"
    item.commercial_reason = "Item autorizado comercialmente."
    recalculate_order_totals(db, order)
    refresh_order_approval_stage(db, order)
    sync_order_balance_ledger(db, order)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.post("/orders/{order_id}/items/{item_id}/cancel", response_model=SalesOrderRead, tags=["Pedidos"])
def cancel_order_item(order_id: int, item_id: int, payload: SalesOrderItemCancel, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    item = db.get(SalesOrderItem, item_id)
    if not item or item.order_id != order.id:
        raise HTTPException(status_code=404, detail="Item do pedido nao encontrado")
    cancel_qty = Decimal(str(payload.quantity or 0))
    if cancel_qty <= 0:
        raise HTTPException(status_code=400, detail="Quantidade de cancelamento deve ser maior que zero")
    remaining = effective_quantity(item)
    if cancel_qty > remaining:
        raise HTTPException(status_code=400, detail="Quantidade de cancelamento maior que o saldo do item")
    linked_quantity = linked_quantity_for_order_item(db, item.id)
    if linked_quantity > 0 and remaining - cancel_qty < linked_quantity:
        raise HTTPException(status_code=400, detail="Cancelamento deixaria o item menor que a quantidade ja baixada no Flow")
    was_submitted = order.approval_stage != "draft"
    item.cancelled_quantity = Decimal(str(item.cancelled_quantity or 0)) + cancel_qty
    recalculate_order_item(item)
    recalculate_order_totals(db, order)
    revalidate_order_if_submitted(db, order, was_submitted)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.post("/orders/{order_id}/cancel", response_model=SalesOrderRead, tags=["Pedidos"])
def cancel_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    for item in db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id)).all():
        if linked_quantity_for_order_item(db, item.id) > 0:
            raise HTTPException(status_code=400, detail="Pedido com baixa vinculada no Flow nao pode ser cancelado")
        item.cancelled_quantity = item.quantity
        recalculate_order_item(item)
    recalculate_order_totals(db, order)
    order.status = "cancelled"
    order.approval_stage = "cancelled"
    order.approval_notes = "Pedido cancelado."
    sync_order_balance_ledger(db, order)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.post("/orders/{order_id}/reject", response_model=SalesOrderRead, tags=["Pedidos"])
def reject_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    order.status = "rejected"
    order.approval_stage = "rejected"
    order.approval_notes = "Pedido rejeitado."
    sync_order_balance_ledger(db, order)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.delete("/orders/{order_id}", tags=["Pedidos"])
def delete_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    items = db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id)).all()
    if any(linked_quantity_for_order_item(db, item.id) > 0 for item in items):
        raise HTTPException(status_code=400, detail="Pedido com baixa vinculada no Flow nao pode ser excluido")
    clear_order_balance_ledger(db, order)
    for payment in db.scalars(select(SalesOrderPayment).where(SalesOrderPayment.order_id == order.id)).all():
        db.delete(payment)
    db.flush()
    for item in items:
        db.delete(item)
    db.flush()
    db.delete(order)
    db.commit()
    return {"ok": True}

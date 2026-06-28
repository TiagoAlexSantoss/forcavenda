import json
import re
import base64
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, SessionLocal, engine, get_db
from app.license import router as license_router
from app.models import (
    AccessGroup,
    Company,
    CustomerLink,
    CustomerProfile,
    CustomerProfilePaymentRule,
    ModuleSetting,
    PriceTable,
    PriceTableItem,
    PriceTableItemTier,
    Product,
    ProductClass,
    ProductGroup,
    SalesOrder,
    SalesOrderItem,
    SalesOrderPayment,
    SalesRepresentative,
    SalesRepresentativeCustomer,
    User,
    UserHomePreference,
    WhatsappOrderSession,
)
from app.schemas import (
    AuthUserRead,
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
    HomePreferencesRead,
    HomePreferencesUpdate,
    LoginRequest,
    LoginResponse,
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
    SalesRepresentativeAssign,
    SalesRepresentativeCreate,
    SalesRepresentativeCustomerAssign,
    SalesRepresentativeCustomerPage,
    SalesRepresentativeCustomersUpdate,
    SalesRepresentativeRead,
    SalesRepresentativeUpdate,
    SalesRepresentativeWhatsappContext,
    StockBalanceRead,
    StockMovementRead,
    UserOptionRead,
    WhatsappAssistantMessage,
    WhatsappAssistantResponse,
)


settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SALES_PERMISSION_SCOPES = {
    "sales_products": ["view", "create", "edit", "delete"],
    "sales_price_tables": ["view", "create", "edit", "delete"],
    "sales_product_groups": ["view", "create", "edit", "delete"],
    "sales_product_classes": ["view", "create", "edit", "delete"],
    "sales_customers": ["view", "create", "edit", "delete"],
    "sales_customer_profiles": ["view", "create", "edit", "delete"],
    "sales_representatives": ["view", "create", "edit", "delete"],
    "sales_orders": ["view", "create", "edit", "delete"],
    "sales_approvals": ["view", "edit"],
    "sales_customer_management": ["view", "edit"],
    "sales_order_assistant": ["view"],
    "sales_browser_definitions": ["view"],
    "sales_reports": ["view"],
}

HOME_WIDGET_SCOPES = {
    "quick_actions": (),
    "sales_kpis": ("sales_orders", "sales_approvals", "sales_customer_management"),
    "recent_orders": ("sales_orders",),
    "order_board": ("sales_orders",),
    "customer_health": ("sales_customer_management",),
    "commercial_base": ("sales_customers", "sales_products", "sales_price_tables"),
}
DEFAULT_HOME_WIDGETS = list(HOME_WIDGET_SCOPES)

PUBLIC_PATHS = {"/health", "/auth/login", "/assistant/whatsapp/messages", "/license/local-status", "/license/sync"}

SALES_ROUTE_PERMISSIONS = [
    ("sales_browser_definitions", ("/control/browser-definitions",)),
    ("sales_reports", ("/reports/menu",)),
    ("sales_order_assistant", ("/assistant/status",)),
    ("sales_representatives", ("/sales-representatives", "/users/options")),
    ("sales_customer_management", ("/customer-monitoring",)),
    ("sales_customer_profiles", ("/customer-profiles",)),
    ("sales_customers", ("/customers",)),
    ("sales_price_tables", ("/price-tables", "/price-preview")),
    ("sales_product_groups", ("/product-groups",)),
    ("sales_product_classes", ("/product-classes",)),
    ("sales_products", ("/products", "/warehouses", "/stock-balances", "/stock-movements")),
    ("sales_approvals", ("/orders/pending-approval", "/orders/approve", "/orders/reject")),
    ("sales_orders", ("/orders",)),
]


def create_access_token(subject: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": subject, "exp": expires_at}, settings.jwt_secret, algorithm="HS256")


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def full_sales_permissions() -> dict[str, list[str]]:
    return {scope: actions[:] for scope, actions in SALES_PERMISSION_SCOPES.items()}


def user_permissions(db: Session, user: User) -> dict[str, list[str]]:
    if user.role == "admin":
        return full_sales_permissions()
    group = db.get(AccessGroup, user.group_id) if user.group_id else None
    if not group or not group.active:
        return {}
    if group.fixed:
        return full_sales_permissions()
    permissions = group.permissions or {}
    return {
        scope: [action for action in actions if action in permissions.get(scope, [])]
        for scope, actions in SALES_PERMISSION_SCOPES.items()
        if any(action in permissions.get(scope, []) for action in actions)
    }


def available_home_widgets(db: Session, user: User) -> list[str]:
    permissions = user_permissions(db, user)
    view_scopes = {scope for scope, actions in permissions.items() if "view" in actions}
    available = []
    for widget_id, scopes in HOME_WIDGET_SCOPES.items():
        if widget_id == "quick_actions":
            allowed = bool(view_scopes)
        else:
            allowed = any(scope in view_scopes for scope in scopes)
        if allowed:
            available.append(widget_id)
    return available


def sanitize_home_widgets(widget_ids: list[str], available: list[str]) -> list[str]:
    allowed = set(available)
    return list(dict.fromkeys(widget_id for widget_id in widget_ids if widget_id in allowed))


def user_company_ids(db: Session, user: User) -> list[int]:
    if user.role == "admin":
        return list(db.scalars(select(Company.id).where(Company.active == True)).all())
    group = db.get(AccessGroup, user.group_id) if user.group_id else None
    if not group or not group.active:
        return []
    if group.fixed:
        return list(db.scalars(select(Company.id).where(Company.active == True)).all())
    return [
        int(company_id)
        for company_id in db.execute(
            text("SELECT company_id FROM control_access_group_companies WHERE group_id = :group_id AND active = TRUE"),
            {"group_id": user.group_id},
        ).scalars().all()
    ]


def user_from_authorization(db: Session, authorization: str | None) -> User | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(authorization.removeprefix("Bearer ").strip(), settings.jwt_secret, algorithms=["HS256"])
        user_id = payload.get("sub")
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Sessao invalida ou expirada") from exc
    user = db.get(User, int(user_id)) if user_id else None
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Usuario inativo ou nao encontrado")
    return user


def route_permission(path: str, method: str) -> tuple[str, str] | None:
    if method == "OPTIONS" or path in PUBLIC_PATHS or path.startswith(("/docs", "/openapi", "/redoc")):
        return None
    if path in {"/auth/me", "/companies", "/home/preferences", "/reports/available"}:
        return None
    if path.startswith("/reports/") and path.endswith("/print"):
        return None
    action = {"GET": "view", "POST": "create", "PUT": "edit", "PATCH": "edit", "DELETE": "delete"}.get(method)
    if not action:
        return None
    if path.startswith("/orders/") and any(
        marker in path
        for marker in ("/approve-financial", "/approve-commercial", "/reject")
    ):
        return "sales_approvals", "edit"
    for scope, prefixes in SALES_ROUTE_PERMISSIONS:
        if any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes):
            if scope == "sales_approvals" and action != "view":
                action = "edit"
            return scope, action
    return "sales_orders", "view"


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
        {"name": "Vendedores", "description": "Usuarios comerciais, WhatsApp e carteira de clientes."},
        {"name": "Assistente WhatsApp", "description": "Interpretacao e criacao assistida de pedidos via WhatsApp."},
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

app.include_router(license_router)


@app.middleware("http")
async def enforce_access(request: Request, call_next):
    requirement = route_permission(request.url.path, request.method)
    if requirement is None:
        return await call_next(request)
    db = SessionLocal()
    try:
        try:
            user = user_from_authorization(db, request.headers.get("Authorization"))
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        if not user:
            return JSONResponse(status_code=401, content={"detail": "Login obrigatorio"})
        scope, action = requirement
        permissions = user_permissions(db, user)
        allowed = action in (permissions.get(scope) or [])
        if request.method == "GET" and not allowed:
            support_scopes = {
                "sales_products": ("sales_orders",),
                "sales_price_tables": ("sales_orders",),
                "sales_customers": ("sales_orders",),
                "sales_representatives": ("sales_orders",),
                "sales_orders": ("sales_approvals",),
            }
            allowed = any("view" in (permissions.get(candidate) or []) for candidate in support_scopes.get(scope, ()))
        if not allowed:
            return JSONResponse(status_code=403, content={"detail": "Acesso nao permitido para esta operacao"})
        request.state.current_user_id = user.id
        request.state.allowed_company_ids = user_company_ids(db, user)
    finally:
        db.close()
    return await call_next(request)


@app.on_event("startup")
async def startup():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS control_companies (id SERIAL PRIMARY KEY, parent_company_id INTEGER REFERENCES control_companies(id), code VARCHAR(40) UNIQUE NOT NULL, name VARCHAR(160) NOT NULL, legal_name VARCHAR(180), document_number VARCHAR(40), company_kind VARCHAR(20) NOT NULL DEFAULT 'matrix', active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO control_companies (code, name, company_kind, active, created_at, updated_at) SELECT 'MATRIZ', 'Matriz', 'matrix', TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM control_companies)"))
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
        connection.execute(text("ALTER TABLE sf_products ADD COLUMN IF NOT EXISTS suggested_margin_percent NUMERIC(8, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_products ADD COLUMN IF NOT EXISTS default_warehouse_id INTEGER"))
        connection.execute(text("ALTER TABLE sf_products ADD COLUMN IF NOT EXISTS default_warehouse_name VARCHAR(160)"))
        connection.execute(text("CREATE TABLE IF NOT EXISTS flow_product_lot_configs (id SERIAL PRIMARY KEY, product_source VARCHAR(40) NOT NULL, product_external_id VARCHAR(80) NOT NULL, controls_lot BOOLEAN NOT NULL DEFAULT FALSE, lot_type VARCHAR(30) NOT NULL DEFAULT 'none', updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_flow_product_lot_configs_product_external_id ON flow_product_lot_configs (product_external_id)"))
        connection.execute(text("ALTER TABLE sf_customer_links ADD COLUMN IF NOT EXISTS customer_profile_id INTEGER"))
        connection.execute(text("ALTER TABLE people ADD COLUMN IF NOT EXISTS credit_limit NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_representative_customers ADD COLUMN IF NOT EXISTS customer_person_id INTEGER REFERENCES people(id)"))
        connection.execute(text("ALTER TABLE sf_sales_representative_customers ADD COLUMN IF NOT EXISTS customer_link_id INTEGER REFERENCES sf_customer_links(id)"))
        connection.execute(text("UPDATE sf_sales_representative_customers SET customer_person_id = CAST(customer_external_id AS INTEGER) WHERE customer_source = 'easyfinance' AND customer_external_id ~ '^[0-9]+$' AND customer_person_id IS NULL"))
        connection.execute(text("UPDATE sf_sales_representative_customers SET customer_link_id = CAST(customer_external_id AS INTEGER) WHERE customer_source = 'local' AND customer_external_id ~ '^[0-9]+$' AND customer_link_id IS NULL"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_sf_sales_representative_customers_person_id ON sf_sales_representative_customers (customer_person_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_sf_sales_representative_customers_link_id ON sf_sales_representative_customers (customer_link_id)"))
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
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS sales_representative_id INTEGER REFERENCES sf_sales_representatives(id)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_sf_sales_representatives_whatsapp ON sf_sales_representatives (whatsapp_number)"))
        connection.execute(text("CREATE TABLE IF NOT EXISTS control_module_settings (id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES control_companies(id), module_code VARCHAR(80) NOT NULL, settings JSON NOT NULL DEFAULT '{}'::json, active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT uq_control_module_setting UNIQUE (company_id, module_code))"))
        connection.execute(text("UPDATE sf_sales_orders SET company_id = :company_id WHERE company_id IS NULL"), {"company_id": default_company_id})
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_sf_sales_orders_company_status ON sf_sales_orders (company_id, status, approval_stage)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_sf_sales_orders_sales_representative_id ON sf_sales_orders (sales_representative_id)"))
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
        connection.execute(text("ALTER TABLE sf_sales_order_payments ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES control_companies(id)"))
        connection.execute(text("UPDATE sf_sales_order_payments SET company_id = COALESCE((SELECT o.company_id FROM sf_sales_orders o WHERE o.id = sf_sales_order_payments.order_id), :company_id) WHERE company_id IS NULL"), {"company_id": default_company_id})
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_sf_sales_order_payments_company_id ON sf_sales_order_payments (company_id)"))
        flow_balance_ledger_exists = connection.execute(text("SELECT to_regclass('public.flow_balance_ledger')")).scalar()
        if flow_balance_ledger_exists:
            connection.execute(text("ALTER TABLE flow_balance_ledger ALTER COLUMN stock_movement_id DROP NOT NULL"))
            connection.execute(text("ALTER TABLE flow_balance_ledger ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES control_companies(id)"))
            connection.execute(text("UPDATE flow_balance_ledger SET company_id = COALESCE((SELECT o.company_id FROM sf_sales_orders o WHERE CAST(o.id AS VARCHAR) = flow_balance_ledger.source_document_id AND flow_balance_ledger.source_system = 'easysales' AND flow_balance_ledger.source_document_kind = 'sales_order'), :company_id) WHERE company_id IS NULL"), {"company_id": default_company_id})
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_flow_balance_ledger_company_product_warehouse ON flow_balance_ledger (company_id, product_source, product_external_id, warehouse_id, balance_type_id)"))
            connection.execute(text("ALTER TABLE flow_balance_ledger ADD COLUMN IF NOT EXISTS source_system VARCHAR(40)"))
            connection.execute(text("ALTER TABLE flow_balance_ledger ADD COLUMN IF NOT EXISTS source_document_kind VARCHAR(40)"))
            connection.execute(text("ALTER TABLE flow_balance_ledger ADD COLUMN IF NOT EXISTS source_document_id VARCHAR(80)"))
            connection.execute(text("ALTER TABLE flow_balance_ledger ADD COLUMN IF NOT EXISTS source_item_id VARCHAR(80)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_flow_balance_ledger_source_item ON flow_balance_ledger (source_system, source_document_kind, source_item_id)"))
        connection.execute(text("UPDATE sf_sales_orders SET operation_code = 'PV' WHERE order_type = 'sale' AND (operation_code IS NULL OR operation_code = '')"))
        flow_operation_types_exists = connection.execute(text("SELECT to_regclass('public.flow_operation_types')")).scalar()
        if flow_operation_types_exists:
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
    allowed_company_ids = getattr(request.state, "allowed_company_ids", None)
    if allowed_company_ids is not None and company.id not in allowed_company_ids:
        raise HTTPException(status_code=403, detail="Empresa nao liberada para o usuario")
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


def normalize_phone(value: str) -> str:
    phone = "".join(character for character in value if character.isdigit())
    if len(phone) < 10:
        raise HTTPException(status_code=400, detail="Informe um WhatsApp valido com DDD")
    if len(phone) in {10, 11}:
        phone = f"55{phone}"
    return phone


def split_customer_id(customer_id: str) -> tuple[str, str]:
    source, separator, external_id = customer_id.partition(":")
    if not separator or not source or not external_id:
        raise HTTPException(status_code=400, detail="Cliente invalido")
    return source, external_id


def customer_foreign_keys(source: str, external_id: str) -> dict:
    numeric_id = int(external_id) if external_id.isdigit() else None
    return {
        "customer_person_id": numeric_id if source == "easyfinance" else None,
        "customer_link_id": numeric_id if source == "local" else None,
    }


def sales_representative_for_customer(
    db: Session,
    company_id: int,
    source: str,
    external_id: str,
) -> tuple[SalesRepresentative | None, User | None]:
    assignment = db.scalar(
        select(SalesRepresentativeCustomer).where(
            SalesRepresentativeCustomer.company_id == company_id,
            SalesRepresentativeCustomer.customer_source == source,
            SalesRepresentativeCustomer.customer_external_id == external_id,
            SalesRepresentativeCustomer.active == True,
        )
    )
    representative = db.get(SalesRepresentative, assignment.sales_representative_id) if assignment else None
    user = db.get(User, representative.user_id) if representative else None
    return representative, user


def representative_customer_ids(db: Session, representative_id: int) -> list[str]:
    assignments = db.scalars(
        select(SalesRepresentativeCustomer)
        .where(
            SalesRepresentativeCustomer.sales_representative_id == representative_id,
            SalesRepresentativeCustomer.active == True,
        )
        .order_by(
            SalesRepresentativeCustomer.customer_source.asc(),
            SalesRepresentativeCustomer.customer_external_id.asc(),
        )
    ).all()
    return [f"{item.customer_source}:{item.customer_external_id}" for item in assignments]


def representative_to_read(db: Session, item: SalesRepresentative) -> dict:
    user = db.get(User, item.user_id)
    customer_ids = representative_customer_ids(db, item.id)
    return {
        "id": item.id,
        "company_id": item.company_id,
        "user_id": item.user_id,
        "user_name": user.name if user else "Usuario removido",
        "user_email": user.email if user else "",
        "code": item.code,
        "whatsapp_number": item.whatsapp_number,
        "active": item.active,
        "customer_ids": customer_ids,
        "customer_count": len(customer_ids),
    }


def replace_representative_customers(
    db: Session,
    representative: SalesRepresentative,
    customer_ids: list[str],
):
    requested = {split_customer_id(customer_id) for customer_id in customer_ids}
    existing = db.scalars(
        select(SalesRepresentativeCustomer).where(
            SalesRepresentativeCustomer.sales_representative_id == representative.id
        )
    ).all()
    existing_by_customer = {(item.customer_source, item.customer_external_id): item for item in existing}
    for item in existing:
        item.active = (item.customer_source, item.customer_external_id) in requested
    for source, external_id in requested:
        if not person_available_for_company(db, representative.company_id, source, external_id):
            raise HTTPException(status_code=400, detail=f"Cliente {source}:{external_id} nao pertence a empresa")
        assignment = db.scalar(
            select(SalesRepresentativeCustomer).where(
                SalesRepresentativeCustomer.company_id == representative.company_id,
                SalesRepresentativeCustomer.customer_source == source,
                SalesRepresentativeCustomer.customer_external_id == external_id,
            )
        )
        current = existing_by_customer.get((source, external_id))
        if current:
            current.active = True
        elif assignment:
            assignment.sales_representative_id = representative.id
            assignment.active = True
            assignment.customer_person_id = customer_foreign_keys(source, external_id)["customer_person_id"]
            assignment.customer_link_id = customer_foreign_keys(source, external_id)["customer_link_id"]
        else:
            db.add(
                SalesRepresentativeCustomer(
                    company_id=representative.company_id,
                    sales_representative_id=representative.id,
                    customer_source=source,
                    customer_external_id=external_id,
                    active=True,
                    **customer_foreign_keys(source, external_id),
                )
            )


def resolve_order_representative(
    db: Session,
    company_id: int,
    customer_source: str,
    customer_external_id: str,
    representative_id: int | None,
) -> SalesRepresentative | None:
    if representative_id:
        representative = db.get(SalesRepresentative, representative_id)
        if not representative or representative.company_id != company_id or not representative.active:
            raise HTTPException(status_code=400, detail="Vendedor invalido para a empresa ativa")
        assignment, _ = sales_representative_for_customer(
            db, company_id, customer_source, customer_external_id
        )
        if not assignment or assignment.id != representative.id:
            raise HTTPException(status_code=400, detail="Cliente nao pertence a carteira do vendedor")
        return representative
    representative, _ = sales_representative_for_customer(
        db, company_id, customer_source, customer_external_id
    )
    return representative if representative and representative.active else None


def customer_representative_fields(db: Session, company_id: int, source: str, external_id: str) -> dict:
    representative, user = sales_representative_for_customer(db, company_id, source, external_id)
    return {
        "sales_representative_id": representative.id if representative else None,
        "sales_representative_name": user.name if user else None,
    }


ORDER_ASSISTANT_MODULE = "sales-whatsapp-assistant"
ASSISTANT_BOOT_MENU = (
    "Escolha o atendimento:\n"
    "1 - EasySales (precos, catalogo e pedidos)\n"
    "2 - BI (dashboards e indicadores)"
)
ASSISTANT_SESSION_TIMEOUT_MINUTES = 10
ASSISTANT_MAX_SESSION_TIMEOUT_MINUTES = 1440
ASSISTANT_RESET_COMMANDS = {"menu", "inicio", "iniciar", "voltar"}
ASSISTANT_CANCEL_COMMANDS = {"cancelar", "cancela", "cancel", "sair", "encerrar", "parar"}
ASSISTANT_RECENT_PRODUCT_REFERENCE_TERMS = {
    "esse",
    "esses",
    "essas",
    "desses",
    "dessas",
    "este",
    "eles",
    "elas",
    "ambos",
    "ambas",
    "os dois",
    "as duas",
    "estes",
    "estas",
    "destes",
    "destas",
}


def order_assistant_settings(db: Session, company_id: int) -> dict:
    item = db.scalar(
        select(ModuleSetting).where(
            ModuleSetting.company_id == company_id,
            ModuleSetting.module_code == ORDER_ASSISTANT_MODULE,
        )
    )
    defaults = {
        "enabled": False,
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "audio_model": "gemini-2.5-flash-lite",
        "api_key": None,
        "require_confirmation": True,
        "create_as_draft": True,
        "send_order_pdf": False,
        "default_payment_days": 30,
        "price_table_id": None,
        "session_timeout_minutes": 10,
    }
    if not item:
        return defaults
    return {**defaults, **(item.settings or {}), "enabled": bool(item.active)}


def normalize_search(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", ascii_value.lower())).strip()


def best_catalog_match(query: str, rows: list[dict], fields: tuple[str, ...]) -> tuple[dict | None, float]:
    target = normalize_search(query)
    if not target:
        return None, 0
    scored = []
    for row in rows:
        values = [normalize_search(str(row.get(field) or "")) for field in fields]
        exact = next((value for value in values if target == value), None)
        contains = next((value for value in values if target in value or value in target), None)
        score = 1.0 if exact else 0.92 if contains else max(
            (SequenceMatcher(None, target, value).ratio() for value in values if value),
            default=0,
        )
        scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return (scored[0][1], scored[0][0]) if scored else (None, 0)


def extract_json_object(value: str) -> dict:
    text_value = value.strip()
    if text_value.startswith("```"):
        text_value = re.sub(r"^```(?:json)?\s*|\s*```$", "", text_value, flags=re.IGNORECASE)
    start = text_value.find("{")
    end = text_value.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Resposta da IA sem JSON")
    return json.loads(text_value[start:end + 1])


def gemini_extract_order(
    message: str,
    customers: list[dict],
    products: list[dict],
    settings_value: dict,
    recent_products: list[dict] | None = None,
    conversation_history: list[dict] | None = None,
) -> dict:
    api_key = settings_value.get("api_key")
    model = settings_value.get("model") or "gemini-2.5-flash"
    if not api_key:
        raise RuntimeError("Chave da IA nao configurada no EasyControl")
    customer_catalog = [{"id": row["id"], "name": row["name"]} for row in customers]
    product_catalog = [{"id": row["id"], "sku": row["sku"], "name": row["name"]} for row in products]
    recent_product_catalog = [
        {"id": row["id"], "sku": row["sku"], "name": row["name"]}
        for row in (recent_products or [])
    ]
    recent_instruction = (
        "Produtos consultados recentemente nesta sessao: "
        f"{json.dumps(recent_product_catalog, ensure_ascii=False)}. "
        "Se a mensagem usar referencias como 'esses produtos', 'desses', 'eles', 'ambos' ou '2 de cada', "
        "interprete como os produtos consultados recentemente e preencha items com o sku ou nome deles. "
        if recent_product_catalog
        else ""
    )
    history_instruction = (
        "Historico recente desta mesma conversa: "
        f"{json.dumps(conversation_history, ensure_ascii=False)}. "
        "Use o historico para manter cliente, produtos, quantidades e condicoes ja informados. "
        "A mensagem atual tem prioridade quando corrigir, remover, trocar ou acrescentar algo. "
        if conversation_history
        else ""
    )
    prompt = (
        "Extraia um pedido comercial da mensagem. Responda somente JSON valido com: "
        '{"customer":"texto ou null","items":[{"product":"texto","quantity":numero}],'
        '"payment_days":numero ou null,"payment_terms":[numero],"delivery_date":"YYYY-MM-DD ou null"}. '
        "Em payment_terms, preserve todos os prazos informados, por exemplo 30/60/90. "
        "Quando o usuario disser 'de cada', aplique a mesma quantidade a todos os produtos referenciados. "
        "Use payment_days como o maior prazo ou null quando nenhum prazo for informado. "
        f"{recent_instruction}"
        f"{history_instruction}"
        "Nao invente cliente nem produto. Catalogo de clientes: "
        f"{json.dumps(customer_catalog, ensure_ascii=False)}. Catalogo de produtos: "
        f"{json.dumps(product_catalog, ensure_ascii=False)}. Mensagem: {message}"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1200,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    request_data = UrlRequest(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    try:
        with urlopen(request_data, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"IA retornou erro {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError("Nao foi possivel acessar o provedor de IA") from exc
    parts = (body.get("candidates") or [{}])[0].get("content", {}).get("parts") or []
    content = "\n".join(part.get("text", "") for part in parts)
    return extract_json_object(content)


def gemini_transcribe_audio(audio_base64: str, mime_type: str | None, settings_value: dict) -> str:
    api_key = settings_value.get("api_key")
    if not api_key:
        raise RuntimeError("Chave da IA nao configurada no EasyControl")
    try:
        base64.b64decode(audio_base64, validate=True)
    except Exception as exc:
        raise RuntimeError("Audio recebido em formato invalido") from exc
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": "Transcreva este audio em portugues brasileiro. Retorne somente o texto falado."},
                {"inline_data": {"mime_type": mime_type or "audio/ogg", "data": audio_base64}},
            ],
        }],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1200, "thinkingConfig": {"thinkingBudget": 0}},
    }
    configured_model = settings_value.get("model") or "gemini-2.5-flash"
    audio_model = settings_value.get("audio_model") or "gemini-2.5-flash-lite"
    models = list(dict.fromkeys([audio_model, configured_model]))
    quota_exhausted = False

    for model in models:
        request_data = UrlRequest(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        )
        try:
            with urlopen(request_data, timeout=90) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            quota_exhausted = quota_exhausted or exc.code == 429
            continue
        except URLError:
            continue

        parts = (body.get("candidates") or [{}])[0].get("content", {}).get("parts") or []
        transcription = "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()
        if transcription:
            return transcription

    if quota_exhausted:
        raise RuntimeError(
            "O limite temporario da transcricao foi atingido. Aguarde um minuto e tente novamente ou envie por texto."
        )
    raise RuntimeError("Nao consegui entender o audio. Tente novamente ou envie por texto.")


def representative_customers_for_assistant(db: Session, representative: SalesRepresentative) -> list[dict]:
    rows = []
    for customer_id in representative_customer_ids(db, representative.id):
        customer = resolve_customer(db, customer_id)
        rows.append({"id": customer_id, "name": customer["name"]})
    return rows


def assistant_products(db: Session, company_id: int, price_table_id: int) -> list[dict]:
    products = db.scalars(
        select(Product)
        .join(PriceTableItem, PriceTableItem.product_id == Product.id)
        .where(
            Product.active == True,
            PriceTableItem.price_table_id == price_table_id,
            PriceTableItem.active == True,
            text("EXISTS (SELECT 1 FROM control_product_companies pc WHERE pc.company_id = :company_id AND pc.product_source = 'easysales' AND pc.product_external_id = CAST(sf_products.id AS VARCHAR) AND pc.active = TRUE)"),
        )
        .params(company_id=company_id)
        .order_by(Product.name.asc())
    ).all()
    return [{"id": item.id, "sku": item.sku, "name": item.name} for item in products]


def assistant_price_table(db: Session, company_id: int, configured_id: int | None) -> PriceTable:
    if configured_id:
        table = db.get(PriceTable, configured_id)
        if table and table.active and catalog_available_for_company(db, company_id, "sf_price_tables", table.id):
            return table
    table = db.scalar(
        select(PriceTable).where(
            PriceTable.active == True,
            text("EXISTS (SELECT 1 FROM control_catalog_companies cc WHERE cc.company_id = :company_id AND cc.catalog_key = 'sf_price_tables' AND cc.record_id = CAST(sf_price_tables.id AS VARCHAR) AND cc.active = TRUE)"),
        ).params(company_id=company_id).order_by(PriceTable.id.asc())
    )
    if not table:
        raise HTTPException(status_code=400, detail="Nenhuma tabela de preco ativa para a empresa")
    return table


def assistant_product_terms(product: dict) -> list[str]:
    ignored = {"sim", "de", "do", "da", "dos", "das", "para", "com", "sem", "agricola", "semente", "granulada"}
    source = normalize_search(f"{product.get('sku') or ''} {product.get('name') or ''}")
    return [term for term in source.split() if len(term) > 3 and term not in ignored]


def assistant_product_mentioned(product: dict, normalized_message: str) -> bool:
    sku = normalize_search(str(product.get("sku") or ""))
    name = normalize_search(str(product.get("name") or ""))
    if sku and sku in normalized_message:
        return True
    if name and name in normalized_message:
        return True
    return any(term in normalized_message for term in assistant_product_terms(product))


def assistant_customer_match(message: str, customers: list[dict]) -> tuple[dict | None, float]:
    customer, score = best_catalog_match(message, customers, ("id", "name"))
    if customer and score >= 0.72:
        return customer, score
    normalized_message = normalize_search(message)
    scored = []
    ignored = {"sim", "fazenda", "cliente", "mercado"}
    for row in customers:
        terms = [
            term
            for term in normalize_search(str(row.get("name") or "")).split()
            if len(term) > 2 and term not in ignored
        ]
        if not terms:
            continue
        hits = sum(1 for term in terms if term in normalized_message)
        if hits:
            scored.append((hits / len(terms), row))
    scored.sort(key=lambda item: item[0], reverse=True)
    if scored and scored[0][0] >= 0.65:
        return scored[0][1], scored[0][0]
    return customer, score


def assistant_quantity_near_product(product: dict, normalized_message: str) -> Decimal | None:
    positions = []
    for term in [normalize_search(str(product.get("sku") or "")), *assistant_product_terms(product)]:
        if not term:
            continue
        positions.extend(match.start() for match in re.finditer(re.escape(term), normalized_message))
    if not positions:
        return None
    for index in sorted(set(positions), reverse=True):
        before = normalized_message[max(0, index - 50):index]
        matches = re.findall(r"\b(\d+(?:[,.]\d+)?)\b(?:\s+unidades?)?(?:\s+de)?\s*$", before)
        if not matches:
            matches = re.findall(r"\b(\d+(?:[,.]\d+)?)\b", before)
        if matches:
            return Decimal(matches[-1].replace(",", "."))
    return None


def assistant_shared_quantity(normalized_message: str) -> Decimal | None:
    patterns = [
        r"\b(\d+(?:[,.]\d+)?)\s+unidades?\s+cada\b",
        r"\b(\d+(?:[,.]\d+)?)\s+de\s+cada\b",
        r"\b(\d+(?:[,.]\d+)?)\s+cada\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized_message)
        if match:
            return Decimal(match.group(1).replace(",", "."))
    return None


def deterministic_assistant_extraction(
    message: str,
    customers: list[dict],
    products: list[dict],
    recent_products: list[dict],
    settings_value: dict,
) -> dict:
    normalized = normalize_search(message)
    customer, customer_score = assistant_customer_match(message, customers)
    if not customer or customer_score < 0.72:
        raise HTTPException(status_code=400, detail="Nao identifiquei com seguranca o cliente da sua carteira. Informe o nome do cliente.")

    shared_quantity = assistant_shared_quantity(normalized)
    items = []
    references_recent_products = any(term in normalized for term in ASSISTANT_RECENT_PRODUCT_REFERENCE_TERMS)
    if references_recent_products and shared_quantity and recent_products:
        for product in recent_products:
            items.append({"product": product.get("sku") or product.get("name"), "quantity": str(shared_quantity)})

    recent_ids = {int(product.get("id")) for product in recent_products if product.get("id") is not None}
    for product in products:
        if int(product["id"]) in recent_ids and references_recent_products:
            continue
        if not assistant_product_mentioned(product, normalized):
            continue
        quantity = assistant_quantity_near_product(product, normalized)
        if quantity and quantity > 0:
            items.append({"product": product["sku"], "quantity": str(quantity)})

    payment_terms = assistant_extract_payment_terms(normalized)
    return {
        "customer": customer["name"],
        "items": items,
        "payment_days": max(payment_terms) if payment_terms else None,
        "payment_terms": payment_terms,
        "delivery_date": None,
    }


def build_assistant_draft(
    db: Session,
    representative: SalesRepresentative,
    message: str,
    settings_value: dict,
    memory: dict | None = None,
) -> dict:
    customers = representative_customers_for_assistant(db, representative)
    table = assistant_price_table(db, representative.company_id, settings_value.get("price_table_id"))
    products = assistant_products(db, representative.company_id, table.id)
    recent_products = (memory or {}).get("recent_products") or []
    normalized_message = normalize_search(message)
    references_recent_products = any(term in normalized_message for term in ASSISTANT_RECENT_PRODUCT_REFERENCE_TERMS)
    if recent_products and references_recent_products:
        extracted = deterministic_assistant_extraction(message, customers, products, recent_products, settings_value)
    else:
        try:
            extracted = gemini_extract_order(
                message,
                customers,
                products,
                settings_value,
                recent_products=recent_products,
                conversation_history=assistant_conversation_history(memory or {}),
            )
        except RuntimeError as exc:
            if "429" not in str(exc) and "rate" not in str(exc).lower():
                raise
            extracted = deterministic_assistant_extraction(message, customers, products, recent_products, settings_value)
    customer, customer_score = assistant_customer_match(str(extracted.get("customer") or ""), customers)
    if not customer or customer_score < 0.72:
        raise HTTPException(status_code=400, detail="Nao identifiquei com seguranca o cliente da sua carteira. Informe o nome do cliente.")
    resolved_items = []
    raw_items = extracted.get("items") or []
    references_recent_products = any(term in normalized_message for term in ASSISTANT_RECENT_PRODUCT_REFERENCE_TERMS)
    if references_recent_products and recent_products:
        parsed_quantities = [
            Decimal(str(raw_item.get("quantity") or 0))
            for raw_item in raw_items
            if raw_item.get("quantity") is not None
        ]
        shared_quantity = next((quantity for quantity in parsed_quantities if quantity > 0), Decimal("0"))
        vague_products = not raw_items or any(
            any(term in normalize_search(str(raw_item.get("product") or "")) for term in ASSISTANT_RECENT_PRODUCT_REFERENCE_TERMS)
            for raw_item in raw_items
        )
        if shared_quantity > 0:
            recent_raw_items = [
                {"product": product.get("sku") or product.get("name"), "quantity": str(shared_quantity)}
                for product in recent_products
            ]
            if vague_products:
                raw_items = recent_raw_items + [
                    raw_item
                    for raw_item in raw_items
                    if not any(term in normalize_search(str(raw_item.get("product") or "")) for term in ASSISTANT_RECENT_PRODUCT_REFERENCE_TERMS)
                ]
            else:
                existing_products = normalize_search(" ".join(str(raw_item.get("product") or "") for raw_item in raw_items))
                def recent_product_already_present(raw_item: dict) -> bool:
                    product_text = normalize_search(str(raw_item.get("product") or ""))
                    if product_text and product_text in existing_products:
                        return True
                    terms = [
                        term
                        for term in product_text.split()
                        if len(term) > 3
                    ]
                    return bool(terms and any(term in existing_products for term in terms))

                missing_recent_items = [
                    raw_item
                    for raw_item in recent_raw_items
                    if not recent_product_already_present(raw_item)
                ]
                raw_items = missing_recent_items + raw_items
    for raw_item in raw_items:
        quantity = Decimal(str(raw_item.get("quantity") or 0))
        product, score = best_catalog_match(str(raw_item.get("product") or ""), products, ("sku", "name"))
        if not product or score < 0.70 or quantity <= 0:
            raise HTTPException(status_code=400, detail=f"Nao identifiquei produto ou quantidade em: {raw_item.get('product') or 'item'}")
        resolved_items.append({"product_id": product["id"], "sku": product["sku"], "name": product["name"], "quantity": str(quantity)})
    if not resolved_items:
        raise HTTPException(status_code=400, detail="Nao encontrei produtos e quantidades na mensagem.")
    raw_payment_terms = extracted.get("payment_terms") or []
    payment_terms = sorted({
        max(int(value), 0)
        for value in raw_payment_terms
        if value is not None and str(value).strip()
    })
    if not payment_terms:
        payment_terms = [max(int(extracted.get("payment_days") or settings_value.get("default_payment_days") or 30), 0)]
    payment_days = max(payment_terms)
    payment_due_date = date.today() + timedelta(days=max(payment_days, 0))
    total = Decimal("0")
    for item in resolved_items:
        price_item = db.scalar(select(PriceTableItem).where(
            PriceTableItem.price_table_id == table.id,
            PriceTableItem.product_id == item["product_id"],
            PriceTableItem.active == True,
        ))
        if not price_item:
            raise HTTPException(status_code=400, detail=f"Produto {item['sku']} sem preco na tabela {table.name}.")
        quantity = Decimal(item["quantity"])
        unit_price = apply_progressive_discount(
            corrected_price(table, price_item.base_price, payment_due_date),
            applicable_progressive_tier(db, price_item, quantity),
        )
        item["unit_price"] = str(money_round(unit_price))
        item["total"] = str(money_round(unit_price * quantity))
        total += Decimal(item["total"])
    return {
        "customer_id": customer["id"],
        "customer_name": customer["name"],
        "price_table_id": table.id,
        "price_table_name": table.name,
        "payment_days": payment_days,
        "payment_terms": payment_terms,
        "payment_due_date": payment_due_date.isoformat(),
        "delivery_date": extracted.get("delivery_date"),
        "items": resolved_items,
        "total": str(money_round(total)),
    }


def assistant_summary(draft: dict) -> str:
    lines = [f"Cliente: {draft['customer_name']}"]
    lines.extend(
        f"- {item['quantity']} x {item['sku']} {item['name']} = R$ {Decimal(item['total']):.2f}"
        for item in draft["items"]
    )
    lines.append(f"Total: R$ {Decimal(draft['total']):.2f}")
    payment_terms = draft.get("payment_terms") or [draft["payment_days"]]
    lines.append(f"Pagamento: {'/'.join(str(days) for days in payment_terms)} dia(s)")
    lines.append("Responda SIM para criar o pedido ou CANCELAR.")
    return "\n".join(lines)


def assistant_confirmation_requested(normalized_message: str) -> bool:
    return any(
        term in normalized_message
        for term in {"sim", "confirmar", "confirmo", "pode confirmar", "pode criar", "cria o pedido", "fechar pedido"}
    )


def assistant_extract_payment_terms(normalized_message: str) -> list[int]:
    terms = []
    spaced_terms = re.search(r"\b(?:para|pra|em|pagamento)\s+(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})(?:\s|$)", normalized_message)
    if spaced_terms:
        terms.extend(int(value) for value in spaced_terms.groups())
    for match in re.findall(r"\b\d{1,3}(?:\s*/\s*\d{1,3})+\b", normalized_message):
        terms.extend(int(value) for value in re.findall(r"\d{1,3}", match))
    if not terms and any(term in normalized_message for term in ["prazo", "pagamento", "condicao", "condicoes", "boleto", "faz em", "fazer em"]):
        terms.extend(int(value) for value in re.findall(r"\b\d{1,3}\b", normalized_message))
    if not terms and assistant_confirmation_requested(normalized_message):
        numbers = [int(value) for value in re.findall(r"\b\d{1,3}\b", normalized_message)]
        if len(numbers) > 1:
            terms.extend(numbers)
    return sorted({max(value, 0) for value in terms})


def recalculate_assistant_draft_totals(db: Session, draft: dict, payment_terms: list[int] | None = None) -> dict:
    table = get_price_table_or_404(db, int(draft["price_table_id"]))
    if payment_terms:
        draft["payment_terms"] = payment_terms
        draft["payment_days"] = max(payment_terms)
    payment_days = int(draft.get("payment_days") or 0)
    payment_due_date = date.today() + timedelta(days=max(payment_days, 0))
    draft["payment_due_date"] = payment_due_date.isoformat()
    total = Decimal("0")
    for item in draft.get("items") or []:
        price_item = db.scalar(select(PriceTableItem).where(
            PriceTableItem.price_table_id == table.id,
            PriceTableItem.product_id == int(item["product_id"]),
            PriceTableItem.active == True,
        ))
        if not price_item:
            raise HTTPException(status_code=400, detail=f"Produto {item.get('sku') or item.get('name')} sem preco na tabela {table.name}.")
        quantity = Decimal(str(item["quantity"]))
        unit_price = apply_progressive_discount(
            corrected_price(table, price_item.base_price, payment_due_date),
            applicable_progressive_tier(db, price_item, quantity),
        )
        item["unit_price"] = str(money_round(unit_price))
        item["total"] = str(money_round(unit_price * quantity))
        total += Decimal(item["total"])
    draft["total"] = str(money_round(total))
    return draft


def assistant_item_matches_terms(item: dict, terms: list[str]) -> bool:
    haystack = normalize_search(f"{item.get('sku') or ''} {item.get('name') or ''}")
    return any(term and (term in haystack or haystack in term) for term in terms)


def remove_assistant_draft_items(draft: dict, message_text: str) -> tuple[dict, bool]:
    normalized = normalize_search(message_text)
    remove_terms = ["tirar", "tira", "remove", "remover", "excluir", "exclui", "sem", "nao pedi", "nao incluir"]
    if not any(term in normalized for term in remove_terms):
        return draft, False
    ignored = {
        "a", "as", "de", "do", "dos", "da", "das", "e", "o", "os", "um", "uma",
        "pedi", "pedido", "produto", "produtos", "item", "itens", "pode", "por",
        "favor", "pagamento", "prazo", "condicao", "condicoes", "tirar", "tira",
        "remove", "remover", "excluir", "exclui", "sem", "nao", "incluir",
    }
    terms = [term for term in normalized.split() if len(term) > 2 and term not in ignored and not term.isdigit()]
    if not terms:
        return draft, False
    kept_items = [
        item
        for item in draft.get("items") or []
        if not assistant_item_matches_terms(item, terms)
    ]
    if len(kept_items) == len(draft.get("items") or []):
        return draft, False
    if not kept_items:
        raise HTTPException(status_code=400, detail="A alteracao removeria todos os itens do pedido.")
    draft["items"] = kept_items
    return draft, True


def apply_assistant_draft_update(db: Session, draft: dict, message_text: str) -> tuple[dict, bool]:
    normalized = normalize_search(message_text)
    changed = False
    draft, removed_items = remove_assistant_draft_items(draft, message_text)
    if removed_items:
        changed = True
    payment_terms = assistant_extract_payment_terms(normalized)
    if payment_terms:
        draft = recalculate_assistant_draft_totals(db, draft, payment_terms)
        changed = True
    elif changed:
        draft = recalculate_assistant_draft_totals(db, draft)
    return draft, changed


def assistant_requests_contextual_item_update(draft: dict, message_text: str) -> bool:
    normalized = normalize_search(message_text)
    item_mentioned = any(
        assistant_product_mentioned(item, normalized)
        for item in draft.get("items") or []
    )
    adds_or_replaces = any(
        term in normalized
        for term in ("adicion", "inclu", "acrescent", "troca", "substitu")
    )
    changes_quantity = item_mentioned and bool(re.search(r"\b\d+(?:[,.]\d+)?\b", normalized))
    return adds_or_replaces or changes_quantity


def is_assistant_catalog_request(normalized_message: str) -> bool:
    catalog_commands = (
        "catalogo",
        "lista de preco",
        "tabela de preco",
        "tabela vigente",
    )
    price_terms = (
        "cotacao",
        "cotar",
        "quanto custa",
        "preco",
        "precos",
        "valor",
        "valores",
    )
    return any(command in normalized_message for command in catalog_commands + price_terms)


def assistant_module_from_message(normalized_message: str) -> str | None:
    sales_choices = {"1", "sales", "easysales", "easy sales", "vendas", "pedido", "pedidos"}
    bi_choices = {"2", "bi", "portal bi", "dashboard", "dashboards", "indicador", "indicadores"}
    if normalized_message in sales_choices:
        return "sales"
    if normalized_message in bi_choices:
        return "bi"
    return None


def assistant_session_module(session: WhatsappOrderSession | None) -> str | None:
    if session and session.state == "awaiting_confirmation":
        return "sales"
    return (session.draft or {}).get("selected_module") if session else None


def assistant_session_timeout_minutes(settings_value: dict) -> int:
    return min(
        max(int(settings_value.get("session_timeout_minutes") or ASSISTANT_SESSION_TIMEOUT_MINUTES), 1),
        ASSISTANT_MAX_SESSION_TIMEOUT_MINUTES,
    )


def assistant_session_notice(minutes: int) -> str:
    return f"\n\nVou manter esta conversa aberta por {minutes} min sem atividade. Se quiser encerrar antes, envie CANCELAR."


def assistant_session_memory(session: WhatsappOrderSession | None) -> dict:
    return dict(session.draft or {}) if session and isinstance(session.draft, dict) else {}


def assistant_conversation_history(memory: dict) -> list[dict]:
    history = memory.get("conversation_history") or []
    if not isinstance(history, list):
        return []
    cleaned = []
    for turn in history[-12:]:
        if not isinstance(turn, dict) or turn.get("role") not in {"user", "assistant"}:
            continue
        content = str(turn.get("content") or "").strip()
        if content:
            cleaned.append({"role": turn["role"], "content": content[:1200]})
    return cleaned


def remember_assistant_turn(memory: dict, role: str, content: str) -> dict:
    history = assistant_conversation_history(memory)
    text_value = str(content or "").strip()
    if text_value:
        history.append({"role": role, "content": text_value[:1200]})
    memory["conversation_history"] = history[-12:]
    return memory


def assistant_recent_products(memory: dict) -> list[dict]:
    products = memory.get("recent_products") or []
    if not isinstance(products, list):
        return []
    cleaned = []
    for product in products[:10]:
        if not isinstance(product, dict):
            continue
        try:
            product_id = int(product.get("id") or product.get("product_id"))
        except (TypeError, ValueError):
            continue
        cleaned.append(
            {
                "id": product_id,
                "sku": str(product.get("sku") or ""),
                "name": str(product.get("name") or ""),
            }
        )
    return cleaned


def assistant_pending_order_message(memory: dict) -> str | None:
    value = memory.get("pending_order_message")
    return str(value).strip() if value else None


def is_assistant_incomplete_order_error(detail: str) -> bool:
    normalized = normalize_search(detail)
    return any(
        marker in normalized
        for marker in (
            "nao identifiquei com seguranca o cliente",
            "nao identifiquei produto ou quantidade",
            "nao encontrei produtos e quantidades",
        )
    )


def assistant_order_followup_message(memory: dict, message_text: str) -> str:
    pending = assistant_pending_order_message(memory)
    if not pending:
        return message_text
    normalized = normalize_search(message_text)
    if normalized in ASSISTANT_RESET_COMMANDS or normalized in ASSISTANT_CANCEL_COMMANDS:
        return message_text
    return f"{pending}\nComplemento do usuario: {message_text}"


def assistant_draft_update_message(draft: dict, instruction: str) -> str:
    items = "; ".join(
        f"{item.get('quantity')} x {item.get('sku')} {item.get('name')}"
        for item in draft.get("items") or []
    )
    payment_terms = draft.get("payment_terms") or [draft.get("payment_days")]
    payment = "/".join(str(value) for value in payment_terms if value is not None)
    return (
        f"Pedido atual: cliente {draft.get('customer_name')}; itens: {items}; pagamento: {payment} dias. "
        f"Nova mensagem do usuario: {instruction}. "
        "Retorne o pedido completo depois de aplicar a nova mensagem. Preserve exatamente os dados que ela nao alterou."
    )


def save_assistant_session_memory(
    db: Session,
    representative: SalesRepresentative,
    phone: str,
    memory: dict,
    message_text: str,
    expires_at: datetime,
    session: WhatsappOrderSession | None = None,
) -> WhatsappOrderSession:
    if not session:
        session = WhatsappOrderSession(
            company_id=representative.company_id,
            sales_representative_id=representative.id,
            whatsapp_number=phone,
            state="collecting",
            draft={},
            expires_at=expires_at,
        )
        db.add(session)
    session.state = "collecting"
    session.draft = memory
    session.last_message = message_text
    session.expires_at = expires_at
    close_other_assistant_sessions(db, representative, phone, session)
    db.commit()
    return session


def close_other_assistant_sessions(
    db: Session,
    representative: SalesRepresentative,
    phone: str,
    keep_session: WhatsappOrderSession | None = None,
) -> None:
    query = select(WhatsappOrderSession).where(
        WhatsappOrderSession.sales_representative_id == representative.id,
        WhatsappOrderSession.whatsapp_number == phone,
        WhatsappOrderSession.state.in_(["collecting", "awaiting_confirmation"]),
    )
    if keep_session and keep_session.id:
        query = query.where(WhatsappOrderSession.id != keep_session.id)
    for old_session in db.scalars(query).all():
        old_session.state = "expired"
        old_session.draft = {}


def save_assistant_module_session(
    db: Session,
    representative: SalesRepresentative,
    phone: str,
    selected_module: str | None,
    message_text: str,
    expires_at: datetime,
    session: WhatsappOrderSession | None = None,
) -> WhatsappOrderSession:
    memory = {"selected_module": selected_module} if selected_module else {}
    return save_assistant_session_memory(db, representative, phone, memory, message_text, expires_at, session)


def assistant_catalog(db: Session, representative: SalesRepresentative, settings_value: dict, message: str) -> tuple[str, list[dict]]:
    table = assistant_price_table(db, representative.company_id, settings_value.get("price_table_id"))
    products = assistant_products(db, representative.company_id, table.id)
    normalized = normalize_search(message)
    ignored_terms = {
        "a", "ao", "as", "catalogo", "da", "das", "de", "do", "dos", "e", "envia",
        "enviar", "envie", "favor", "me", "manda", "mandar", "mim", "mostra", "mostrar",
        "o", "os", "para", "poder", "por", "preco", "precos", "produto", "produtos",
        "qual", "que", "quero", "tambem", "tabela", "um", "uma", "ver", "vigente",
    }
    query_terms = [token for token in normalized.split() if token not in ignored_terms]
    if query_terms:
        def matches_query(product: dict) -> bool:
            product_terms = normalize_search(f"{product['sku']} {product['name']}").split()
            return any(
                query_term in product_term
                or product_term in query_term
                or SequenceMatcher(None, query_term, product_term).ratio() >= 0.82
                for query_term in query_terms
                for product_term in product_terms
            )

        products = [
            product for product in products
            if matches_query(product)
        ]
    if not products:
        return f"Nao encontrei produtos para essa busca na tabela {table.name}.", []
    default_payment_days = int(settings_value.get("default_payment_days") or 30)
    due_date = date.today() + timedelta(days=default_payment_days)
    lines = [
        f"Catalogo vigente: {table.code} - {table.name}",
        f"Valores corrigidos para vencimento em {default_payment_days} dia(s). Entre parenteses, preco a vista/base da tabela.",
    ]
    for product in products[:30]:
        item = db.scalar(select(PriceTableItem).where(
            PriceTableItem.price_table_id == table.id,
            PriceTableItem.product_id == product["id"],
            PriceTableItem.active == True,
        ))
        if not item:
            continue
        corrected = money_round(corrected_price(table, item.base_price, due_date))
        base_price = money_round(item.base_price)
        lines.append(f"- {product['sku']} | {product['name']} | R$ {corrected:.2f} (a vista/base: R$ {base_price:.2f})")
    if len(products) > 30:
        lines.append(f"Mostrando 30 de {len(products)} produtos. Envie 'catalogo' com o nome para filtrar.")
    return "\n".join(lines), products[:10]


def create_order_from_assistant(db: Session, representative: SalesRepresentative, draft: dict) -> SalesOrder:
    customer = resolve_customer(db, draft["customer_id"])
    table = get_price_table_or_404(db, int(draft["price_table_id"]))
    order = SalesOrder(
        company_id=representative.company_id,
        sales_representative_id=representative.id,
        order_number=next_order_number(db),
        order_type="sale",
        customer_source=customer["source"],
        customer_external_id=customer["external_id"],
        customer_name=customer["name"],
        price_table_id=table.id,
        order_date=date.today(),
        payment_due_date=date.fromisoformat(draft["payment_due_date"]),
        delivery_date=date.fromisoformat(draft["delivery_date"]) if draft.get("delivery_date") else None,
        status="draft",
        approval_stage="draft",
        total_amount=Decimal("0"),
        total_cost_amount=Decimal("0"),
        gross_profit_amount=Decimal("0"),
        profitability_percent=Decimal("0"),
        notes="Pedido criado pelo Assistente de Pedidos via WhatsApp.",
    )
    db.add(order)
    db.flush()
    sales_order_operation(db, order)
    payload_items = [
        SalesOrderItemCreate(product_id=item["product_id"], quantity=Decimal(item["quantity"]))
        for item in draft["items"]
    ]
    build_order_items(db, order, table, payload_items, order.payment_due_date)
    recalculate_order_totals(db, order)
    payment_terms = draft.get("payment_terms") or [int(draft.get("payment_days") or 0)]
    installment_count = len(payment_terms)
    installment_amount = money_round(order.total_amount / installment_count)
    allocated_amount = Decimal("0")
    for index, payment_days in enumerate(payment_terms):
        amount = order.total_amount - allocated_amount if index == installment_count - 1 else installment_amount
        allocated_amount += amount
        db.add(SalesOrderPayment(
            company_id=order.company_id,
            order_id=order.id,
            payment_method="avista" if int(payment_days) == 0 else "boleto",
            due_date=date.today() + timedelta(days=int(payment_days)),
            amount=amount,
            notes="Sugestao gerada pelo Assistente de Pedidos via WhatsApp.",
        ))
    return order


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
        "suggested_margin_percent": item.suggested_margin_percent,
        "sale_price": item.sale_price,
        "default_warehouse_id": item.default_warehouse_id,
        "default_warehouse_name": item.default_warehouse_name,
        "controls_lot": bool(lot_config["controls_lot"]) if lot_config else False,
        "lot_type": lot_config["lot_type"] if lot_config else "none",
        "description": item.description,
        "active": item.active,
        "company_ids": company_ids_for_product(db, item.id),
    }


def suggested_sale_price(cost_price: Decimal, margin_percent: Decimal) -> Decimal:
    cost = Decimal(str(cost_price or 0))
    margin = Decimal(str(margin_percent or 0))
    return cost * (Decimal("1") + (margin / Decimal("100")))


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
    representative = db.get(SalesRepresentative, order.sales_representative_id) if order.sales_representative_id else None
    representative_user = db.get(User, representative.user_id) if representative else None
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
        "sales_representative_id": order.sales_representative_id,
        "sales_representative_name": representative_user.name if representative_user else None,
        "sales_representative_whatsapp": representative.whatsapp_number if representative else None,
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


def report_template_body(db: Session, code: str) -> str:
    try:
        template = db.execute(
            text(
                """
                SELECT template_body
                FROM control_report_definitions
                WHERE code = :code
                  AND active = TRUE
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"code": code},
        ).scalar()
    except SQLAlchemyError:
        template = None
    if not template:
        raise HTTPException(
            status_code=404,
            detail="Modelo de relatorio nao encontrado. Abra o EasyControl uma vez para executar o seed de relatorios.",
        )
    return template


def jsreport_request(path: str, payload: dict, timeout: int = 90) -> tuple[bytes, str]:
    base_url = settings.jsreport_url.rstrip("/")
    body = json.dumps(payload, default=str).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if settings.jsreport_username and settings.jsreport_password:
        credentials = f"{settings.jsreport_username}:{settings.jsreport_password}".encode("utf-8")
        headers["Authorization"] = f"Basic {base64.b64encode(credentials).decode('ascii')}"
    request = UrlRequest(f"{base_url}{path}", data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read(), response.headers.get("content-type", "application/pdf")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:500]
        raise HTTPException(status_code=502, detail=f"jsreport retornou erro {exc.code}: {detail}") from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"jsreport indisponivel: {exc.reason}") from exc


SALES_REPORT_JSREPORT_HELPERS = r"""
function valueOf(row, field) {
  if (!row || !field) return null
  return row[field]
}
function groupValue(value, mode) {
  if (value === null || value === undefined || value === '') return '(Sem valor)'
  if (mode === 'value') return String(value)
  var text = String(value)
  var match = text.match(/^(\d{4})-(\d{2})-(\d{2})/)
  var date = match ? new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))) : new Date(value)
  if (Number.isNaN(date.getTime())) return text
  if (mode === 'year') return String(date.getUTCFullYear())
  if (mode === 'month') return date.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric', timeZone: 'UTC' })
  if (mode === 'day') return date.toLocaleDateString('pt-BR', { timeZone: 'UTC' })
  return text
}
function groupRows(rows, field, mode, direction) {
  var groups = []
  var positions = Object.create(null)
  ;(rows || []).forEach(function (row) {
    var key = groupValue(valueOf(row, field), mode || 'value')
    if (positions[key] === undefined) {
      positions[key] = groups.length
      groups.push({ key: key, rows: [] })
    }
    groups[positions[key]].rows.push(row)
  })
  groups.sort(function (left, right) {
    var comparison = String(left.key).localeCompare(String(right.key), 'pt-BR', { numeric: true, sensitivity: 'base' })
    return direction === 'desc' ? -comparison : comparison
  })
  return groups
}
function rowCount(rows) { return (rows || []).length }
function numberOf(value) {
  if (value === null || value === undefined || value === '') return 0
  if (typeof value === 'number') return value
  var normalized = String(value).replace(/[^\d,.-]/g, '').replace(/\./g, '').replace(',', '.')
  var parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : 0
}
function evalExpression(expression, row) {
  var scope = row || {}
  var keys = Object.keys(scope).filter(function (key) { return /^[A-Za-z_][A-Za-z0-9_]*$/.test(key) })
  var values = keys.map(function (key) { return numberOf(scope[key]) })
  try { return Function(keys.join(','), '"use strict"; return (' + expression + ')').apply(null, values) }
  catch (e) { return 0 }
}
function formatValue(value, format) {
  if (format === 'number') return numberOf(value).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
  if (format === 'money') return numberOf(value).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
  if (format === 'date' && value) {
    var date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('pt-BR')
  }
  return value === null || value === undefined ? '' : value
}
function fmt(field, format, row) { return formatValue(valueOf(row, field), format) }
function fmtCalc(expression, format, row) { return formatValue(evalExpression(expression, row), format) }
function fmtSum(rows, field, format) {
  var total = (rows || []).reduce(function (sum, row) { return sum + numberOf(valueOf(row, field)) }, 0)
  return formatValue(total, format)
}
function fmtSumCalc(rows, expression, format) {
  var total = (rows || []).reduce(function (sum, row) { return sum + numberOf(evalExpression(expression, row)) }, 0)
  return formatValue(total, format)
}
"""


def render_sales_order_pdf(db: Session, order: SalesOrder) -> tuple[bytes, str]:
    template = report_template_body(db, "sales_order_pdf")
    return jsreport_request(
        "/api/report",
        {
            "template": {
                "content": template,
                "engine": "handlebars",
                "recipe": "chrome-pdf",
                "chrome": {"printBackground": True, "format": "A4"},
            },
            "data": sales_order_report_data(db, order),
        },
    )


def sales_screen_report(db: Session, report_id: int, target_screen: str) -> dict:
    report = db.execute(
        text(
            """
            SELECT id, code, name, COALESCE(menu_label, name) AS menu_label,
                   template_body, output_format, data_sql, source_mode, target_screen,
                   COALESCE(print_scope, 'list') AS print_scope
            FROM control_report_definitions
            WHERE id = :report_id
              AND active = TRUE
              AND target_app = 'easysales'
              AND target_screen = :target_screen
            """
        ),
        {"report_id": report_id, "target_screen": target_screen},
    ).mappings().first()
    if not report or not (report.get("template_body") or "").strip():
        raise HTTPException(status_code=404, detail="Relatorio ativo nao encontrado para esta tela.")
    return dict(report)


def render_sales_order_report(db: Session, order: SalesOrder, report: dict) -> tuple[bytes, str]:
    output_format = report.get("output_format") or "pdf"
    recipe = "chrome-pdf" if output_format == "pdf" else "html"
    template = {
        "content": report["template_body"],
        "engine": "handlebars",
        "recipe": recipe,
        "helpers": SALES_REPORT_JSREPORT_HELPERS,
    }
    if output_format == "pdf":
        template["chrome"] = {"printBackground": True, "format": "A4"}
    return jsreport_request(
        "/api/report",
        {"template": template, "data": sales_order_report_data(db, order)},
    )


def sales_report_query_data(db: Session, report: dict) -> dict:
    query = str(report.get("data_sql") or "").strip().rstrip(";")
    lowered = query.lower()
    forbidden = (" insert ", " update ", " delete ", " drop ", " alter ", " create ", " truncate ", " grant ", " revoke ", " call ", " execute ")
    if not query or not (lowered.startswith("select") or lowered.startswith("with")):
        raise HTTPException(status_code=400, detail="O relatorio nao possui uma SQL de leitura valida.")
    if ";" in query or any(token in f" {lowered} " for token in forbidden):
        raise HTTPException(status_code=400, detail="A SQL do relatorio deve conter apenas consulta de leitura.")
    result = db.execute(text(f"SELECT * FROM ({query}) AS easysales_report LIMIT 5000"))
    columns = list(result.keys())
    rows = [dict(row) for row in result.mappings().all()]
    return {
        "title": report.get("menu_label") or report.get("name") or "Relatorio",
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "columns": columns,
        "rows": rows,
    }


def render_sales_list_report(db: Session, report: dict) -> tuple[bytes, str]:
    output_format = report.get("output_format") or "pdf"
    recipe = "chrome-pdf" if output_format == "pdf" else "html"
    template = {
        "content": report["template_body"],
        "engine": "handlebars",
        "recipe": recipe,
        "helpers": SALES_REPORT_JSREPORT_HELPERS,
    }
    if output_format == "pdf":
        template["chrome"] = {"printBackground": True, "format": "A4"}
    return jsreport_request(
        "/api/report",
        {"template": template, "data": sales_report_query_data(db, report)},
        timeout=120,
    )


def send_evolution_document(
    whatsapp_number: str,
    content: bytes,
    filename: str,
    caption: str,
    instance_name: str,
) -> None:
    instance = (instance_name or "").strip()
    if not instance or not re.fullmatch(r"[A-Za-z0-9_-]+", instance):
        raise RuntimeError("Instancia Evolution invalida")
    payload = {
        "number": normalize_phone(whatsapp_number),
        "mediatype": "document",
        "mimetype": "application/pdf",
        "fileName": filename,
        "caption": caption,
        "media": base64.b64encode(content).decode("ascii"),
    }
    request_data = UrlRequest(
        f"{settings.evolution_base_url.rstrip('/')}/message/sendMedia/{instance}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "apikey": settings.evolution_api_key},
    )
    try:
        with urlopen(request_data, timeout=90) as response:
            response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:500]
        raise RuntimeError(f"Evolution retornou erro {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Evolution indisponivel: {exc.reason}") from exc


def send_evolution_text_message(whatsapp_number: str, message: str, instance_name: str) -> None:
    instance = (instance_name or "").strip()
    if not instance or not re.fullmatch(r"[A-Za-z0-9_-]+", instance):
        raise RuntimeError("Instancia Evolution invalida")
    request_data = UrlRequest(
        f"{settings.evolution_base_url.rstrip('/')}/message/sendText/{instance}",
        data=json.dumps({"number": normalize_phone(whatsapp_number), "text": message}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "apikey": settings.evolution_api_key},
    )
    with urlopen(request_data, timeout=30) as response:
        response.read()


def send_assistant_order_pdf_background(order_id: int, representative_id: int, instance_name: str) -> None:
    db = SessionLocal()
    representative = None
    try:
        order = db.get(SalesOrder, order_id)
        representative = db.get(SalesRepresentative, representative_id)
        if not order or not representative:
            raise RuntimeError("Pedido ou vendedor nao encontrado para envio do PDF")
        content, _content_type = render_sales_order_pdf(db, order)
        send_evolution_document(
            representative.whatsapp_number,
            content,
            f"pedido-{order.order_number}.pdf",
            f"Pedido {order.order_number} - {order.customer_name}",
            instance_name,
        )
    except Exception as exc:
        print(f"[assistant][pdf] pedido={order_id} falha={exc}", flush=True)
        if representative:
            try:
                send_evolution_text_message(
                    representative.whatsapp_number,
                    "Nao consegui enviar o PDF do pedido agora. O pedido continua salvo e disponivel no EasySales.",
                    instance_name,
                )
            except Exception as notify_exc:
                print(f"[assistant][pdf] falha ao avisar vendedor={representative_id}: {notify_exc}", flush=True)
    finally:
        db.close()


def schedule_assistant_order_pdf(
    background_tasks: BackgroundTasks,
    order: SalesOrder,
    representative: SalesRepresentative,
    settings_value: dict,
) -> str:
    if not settings_value.get("send_order_pdf", False):
        return ""
    background_tasks.add_task(
        send_assistant_order_pdf_background,
        order.id,
        representative.id,
        settings_value.get("evolution_instance") or "sales-teste",
    )
    return "\n\nVou gerar e enviar o PDF do pedido por aqui."


def format_report_date(value: date | datetime | None) -> str:
    if not value:
        return ""
    return value.strftime("%d/%m/%Y")


def format_report_money(value: Decimal | int | float | None) -> str:
    amount = Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def format_report_decimal(value: Decimal | int | float | None) -> str:
    amount = Decimal(str(value or 0)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    text_value = f"{amount:,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text_value.rstrip("0").rstrip(",")


def payment_method_label(value: str | None) -> str:
    return {
        "avista": "A vista",
        "parcelado": "Parcelado",
        "adiantamento": "Adiantamento",
        "boleto": "Boleto",
    }.get((value or "").lower(), value or "-")


def order_status_label(value: str | None) -> str:
    return {
        "draft": "Rascunho",
        "pending_financial": "Aguardando financeiro",
        "financial_blocked": "Bloqueado financeiro",
        "pending_commercial": "Aguardando comercial",
        "approved": "Aprovado",
        "rejected": "Rejeitado",
        "cancelled": "Cancelado",
    }.get((value or "").lower(), value or "-")


def commercial_status_label(value: str | None) -> str:
    return {
        "approved": "Liberado",
        "pending": "Pendente",
        "rejected": "Rejeitado",
    }.get((value or "").lower(), value or "-")


def sales_order_report_data(db: Session, order: SalesOrder) -> dict:
    company = db.get(Company, order.company_id) if order.company_id else None
    customer = resolve_customer(db, f"{order.customer_source}:{order.customer_external_id}")
    items = db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id).order_by(SalesOrderItem.id.asc())).all()
    payments = db.scalars(
        select(SalesOrderPayment)
        .where(SalesOrderPayment.order_id == order.id)
        .order_by(SalesOrderPayment.due_date.asc(), SalesOrderPayment.id.asc())
    ).all()
    installments = payments or [
        SalesOrderPayment(
            company_id=order.company_id,
            order_id=order.id,
            payment_method="boleto",
            due_date=order.payment_due_date,
            amount=order.total_amount,
            notes=None,
        )
    ]
    discount_amount = Decimal("0")
    return {
        "company": {
            "initials": "".join(part[:1] for part in (company.name if company else "TAS").split()[:2]).upper() or "TAS",
            "name": company.name if company else "TAS Consultoria",
            "legal_name": company.legal_name if company else "",
            "document_number": company.document_number if company else "",
            "address": "",
            "phone": "",
            "email": "",
        },
        "order": {
            "order_number": order.order_number,
            "order_date": format_report_date(order.order_date),
            "status": order_status_label(order.status),
            "customer_name": order.customer_name,
            "customer_document": customer.get("document_number") or "",
            "customer_city": customer.get("city") or "",
            "customer_state": customer.get("state_code") or "",
            "customer_phone": customer.get("phone") or "",
            "sales_representative_name": order_to_read(db, order).get("sales_representative_name") or "",
            "price_table_name": db.get(PriceTable, order.price_table_id).name if db.get(PriceTable, order.price_table_id) else "",
            "payment_terms": f"{len(installments)} parcela(s)",
            "delivery_date": format_report_date(order.delivery_date),
            "subtotal_amount": format_report_money(order.total_amount + discount_amount),
            "discount_amount": format_report_money(discount_amount),
            "freight_amount": format_report_money(0),
            "total_amount": format_report_money(order.total_amount),
            "notes": order.notes or "",
        },
        "items": [
            {
                "product_sku": item.product_sku,
                "product_name": item.product_name,
                "quantity": format_report_decimal(item.quantity),
                "unit_price": format_report_money(item.negotiated_unit_price or item.corrected_unit_price),
                "discount_amount": format_report_money(0),
                "total_amount": format_report_money(item.total_amount),
                "commercial_status": commercial_status_label(item.commercial_status),
            }
            for item in items
        ],
        "payments": [
            {
                "payment_method": payment_method_label(payment.payment_method),
                "due_date": format_report_date(payment.due_date),
                "amount": format_report_money(payment.amount),
            }
            for payment in installments
        ],
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


@app.post("/auth/login", response_model=LoginResponse, tags=["Sistema"])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower(), User.active == True))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="E-mail ou senha invalidos")
    return LoginResponse(
        access_token=create_access_token(str(user.id)),
        user=AuthUserRead(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            group_id=user.group_id,
            permissions=user_permissions(db, user),
            company_ids=user_company_ids(db, user),
        ),
    )


@app.get("/auth/me", response_model=AuthUserRead, tags=["Sistema"])
def me(request: Request, db: Session = Depends(get_db)):
    user = user_from_authorization(db, request.headers.get("Authorization"))
    if not user:
        raise HTTPException(status_code=401, detail="Login obrigatorio")
    return AuthUserRead(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        group_id=user.group_id,
        permissions=user_permissions(db, user),
        company_ids=user_company_ids(db, user),
    )


@app.get("/home/preferences", response_model=HomePreferencesRead, tags=["Sistema"])
def get_home_preferences(request: Request, db: Session = Depends(get_db)):
    user = user_from_authorization(db, request.headers.get("Authorization"))
    if not user:
        raise HTTPException(status_code=401, detail="Login obrigatorio")
    available = available_home_widgets(db, user)
    preference = db.scalar(select(UserHomePreference).where(UserHomePreference.user_id == user.id))
    saved_widgets = (preference.settings or {}).get("widgets") if preference else None
    widgets = DEFAULT_HOME_WIDGETS if saved_widgets is None else saved_widgets
    return HomePreferencesRead(
        widgets=sanitize_home_widgets(widgets, available),
        available_widgets=available,
    )


@app.put("/home/preferences", response_model=HomePreferencesRead, tags=["Sistema"])
def save_home_preferences(payload: HomePreferencesUpdate, request: Request, db: Session = Depends(get_db)):
    user = user_from_authorization(db, request.headers.get("Authorization"))
    if not user:
        raise HTTPException(status_code=401, detail="Login obrigatorio")
    available = available_home_widgets(db, user)
    widgets = sanitize_home_widgets(payload.widgets, available)
    preference = db.scalar(select(UserHomePreference).where(UserHomePreference.user_id == user.id))
    if not preference:
        preference = UserHomePreference(user_id=user.id, settings={})
        db.add(preference)
    preference.settings = {**(preference.settings or {}), "widgets": widgets}
    preference.updated_at = datetime.utcnow()
    db.commit()
    return HomePreferencesRead(widgets=widgets, available_widgets=available)


@app.get("/health", tags=["Sistema"])
def health():
    return {"ok": True, "service": "easysales", "customer_provider": settings.customer_provider}


@app.get("/companies", response_model=list[CompanyRead], tags=["Sistema"])
def list_companies(request: Request, db: Session = Depends(get_db)):
    user = user_from_authorization(db, request.headers.get("Authorization"))
    if not user:
        raise HTTPException(status_code=401, detail="Login obrigatorio")
    allowed = user_company_ids(db, user)
    if not allowed:
        return []
    return db.scalars(
        select(Company)
        .where(Company.active == True, Company.id.in_(allowed))
        .order_by(Company.company_kind.desc(), Company.name.asc())
    ).all()


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
                JOIN control_platforms p ON p.id = e.platform_id
                LEFT JOIN control_browser_columns c ON c.browser_id = b.id AND c.active = TRUE
                LEFT JOIN control_metadata_fields f ON f.id = c.field_id AND f.active = TRUE
                WHERE p.code = 'easysales'
                  AND p.active = TRUE
                  AND b.active = TRUE
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


@app.get("/users/options", response_model=list[UserOptionRead], tags=["Vendedores"])
def list_user_options(db: Session = Depends(get_db)):
    return db.scalars(select(User).where(User.active == True).order_by(User.name.asc())).all()


@app.get("/sales-representatives", response_model=list[SalesRepresentativeRead], tags=["Vendedores"])
def list_sales_representatives(request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    items = db.scalars(
        select(SalesRepresentative)
        .where(SalesRepresentative.company_id == company_id)
        .order_by(SalesRepresentative.active.desc(), SalesRepresentative.id.asc())
    ).all()
    return [representative_to_read(db, item) for item in items]


@app.post(
    "/sales-representatives",
    response_model=SalesRepresentativeRead,
    status_code=status.HTTP_201_CREATED,
    tags=["Vendedores"],
)
def create_sales_representative(
    payload: SalesRepresentativeCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    company_id = active_company_id(request, db)
    user = db.get(User, payload.user_id)
    if not user or not user.active:
        raise HTTPException(status_code=400, detail="Usuario invalido ou inativo")
    representative = SalesRepresentative(
        company_id=company_id,
        user_id=user.id,
        code=normalize_code(payload.code, "Codigo") if payload.code else None,
        whatsapp_number=normalize_phone(payload.whatsapp_number),
        active=payload.active,
    )
    db.add(representative)
    try:
        db.flush()
        if payload.customer_ids:
            replace_representative_customers(db, representative, payload.customer_ids)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Usuario ou WhatsApp ja cadastrado como vendedor nesta empresa")
    db.refresh(representative)
    return representative_to_read(db, representative)


@app.put("/sales-representatives/{representative_id}", response_model=SalesRepresentativeRead, tags=["Vendedores"])
def update_sales_representative(
    representative_id: int,
    payload: SalesRepresentativeUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    company_id = active_company_id(request, db)
    representative = db.get(SalesRepresentative, representative_id)
    if not representative or representative.company_id != company_id:
        raise HTTPException(status_code=404, detail="Vendedor nao encontrado")
    user = db.get(User, payload.user_id)
    if not user or not user.active:
        raise HTTPException(status_code=400, detail="Usuario invalido ou inativo")
    representative.user_id = user.id
    representative.code = normalize_code(payload.code, "Codigo") if payload.code else None
    representative.whatsapp_number = normalize_phone(payload.whatsapp_number)
    representative.active = payload.active
    try:
        if payload.customer_ids is not None:
            replace_representative_customers(db, representative, payload.customer_ids)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Usuario ou WhatsApp ja cadastrado como vendedor nesta empresa")
    db.refresh(representative)
    return representative_to_read(db, representative)


def customer_directory_sql(where_clause: str = "") -> str:
    return f"""
        SELECT *
        FROM (
            SELECT
                'easyfinance' AS customer_source,
                CAST(p.id AS VARCHAR) AS customer_external_id,
                'EF-' || LPAD(CAST(p.id AS VARCHAR), 6, '0') AS customer_code,
                p.name AS customer_name,
                p.document_number,
                p.city,
                p.state_code
            FROM people p
            JOIN control_person_companies pc
              ON pc.person_source = 'easyfinance'
             AND pc.person_external_id = CAST(p.id AS VARCHAR)
             AND pc.company_id = :company_id
             AND pc.active = TRUE
            WHERE p.is_customer = TRUE AND p.active = TRUE

            UNION ALL

            SELECT
                'local' AS customer_source,
                CAST(c.id AS VARCHAR) AS customer_external_id,
                'LC-' || LPAD(CAST(c.id AS VARCHAR), 6, '0') AS customer_code,
                c.name AS customer_name,
                c.document_number,
                c.city,
                c.state_code
            FROM sf_customer_links c
            JOIN control_person_companies pc
              ON pc.person_source = 'local'
             AND pc.person_external_id = CAST(c.id AS VARCHAR)
             AND pc.company_id = :company_id
             AND pc.active = TRUE
            WHERE c.source = 'local' AND c.active = TRUE
        ) customers
        {where_clause}
    """


@app.get(
    "/sales-representatives/customer-options",
    response_model=SalesRepresentativeCustomerPage,
    tags=["Vendedores"],
)
def search_sales_representative_customer_options(
    request: Request,
    query: str = "",
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    company_id = active_company_id(request, db)
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    search = f"%{query.strip()}%"
    directory = customer_directory_sql(
        """
        WHERE (
            :query = ''
            OR customers.customer_code ILIKE :search
            OR customers.customer_name ILIKE :search
            OR COALESCE(customers.document_number, '') ILIKE :search
            OR COALESCE(customers.city, '') ILIKE :search
        )
        AND NOT EXISTS (
            SELECT 1
            FROM sf_sales_representative_customers src
            WHERE src.company_id = :company_id
              AND src.customer_source = customers.customer_source
              AND src.customer_external_id = customers.customer_external_id
              AND src.active = TRUE
        )
        """
    )
    params = {
        "company_id": company_id,
        "query": query.strip(),
        "search": search,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    total = db.execute(text(f"SELECT COUNT(*) FROM ({directory}) available"), params).scalar() or 0
    rows = db.execute(
        text(
            f"""
            SELECT *
            FROM ({directory}) available
            ORDER BY customer_name ASC, customer_code ASC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).mappings().all()
    return {
        "items": [
            {
                **dict(row),
                "customer_id": f"{row['customer_source']}:{row['customer_external_id']}",
            }
            for row in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max((total + page_size - 1) // page_size, 1),
    }


@app.get(
    "/sales-representatives/{representative_id}/customers",
    response_model=SalesRepresentativeCustomerPage,
    tags=["Vendedores"],
)
def list_sales_representative_customers(
    representative_id: int,
    request: Request,
    query: str = "",
    page: int = 1,
    page_size: int = 30,
    db: Session = Depends(get_db),
):
    company_id = active_company_id(request, db)
    representative = db.get(SalesRepresentative, representative_id)
    if not representative or representative.company_id != company_id:
        raise HTTPException(status_code=404, detail="Vendedor nao encontrado")
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    search = f"%{query.strip()}%"
    directory = customer_directory_sql()
    base_query = f"""
        SELECT
            src.id AS assignment_id,
            customers.*,
            sr.id AS sales_representative_id,
            sr.code AS sales_representative_code,
            u.name AS sales_representative_name
        FROM sf_sales_representative_customers src
        JOIN ({directory}) customers
          ON customers.customer_source = src.customer_source
         AND customers.customer_external_id = src.customer_external_id
        JOIN sf_sales_representatives sr ON sr.id = src.sales_representative_id
        JOIN users u ON u.id = sr.user_id
        WHERE src.company_id = :company_id
          AND src.sales_representative_id = :representative_id
          AND src.active = TRUE
          AND (
              :query = ''
              OR customers.customer_code ILIKE :search
              OR customers.customer_name ILIKE :search
              OR COALESCE(customers.document_number, '') ILIKE :search
          )
    """
    params = {
        "company_id": company_id,
        "representative_id": representative_id,
        "query": query.strip(),
        "search": search,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    total = db.execute(text(f"SELECT COUNT(*) FROM ({base_query}) portfolio"), params).scalar() or 0
    rows = db.execute(
        text(
            f"""
            SELECT *
            FROM ({base_query}) portfolio
            ORDER BY customer_name ASC, customer_code ASC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).mappings().all()
    return {
        "items": [
            {
                **dict(row),
                "customer_id": f"{row['customer_source']}:{row['customer_external_id']}",
            }
            for row in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max((total + page_size - 1) // page_size, 1),
    }


@app.post(
    "/sales-representatives/{representative_id}/customers",
    response_model=SalesRepresentativeCustomerPage,
    tags=["Vendedores"],
)
def add_sales_representative_customer(
    representative_id: int,
    payload: SalesRepresentativeCustomerAssign,
    request: Request,
    db: Session = Depends(get_db),
):
    company_id = active_company_id(request, db)
    representative = db.get(SalesRepresentative, representative_id)
    if not representative or representative.company_id != company_id:
        raise HTTPException(status_code=404, detail="Vendedor nao encontrado")
    source, external_id = split_customer_id(payload.customer_id)
    if not person_available_for_company(db, company_id, source, external_id):
        raise HTTPException(status_code=404, detail="Cliente nao encontrado na empresa ativa")
    assignment = db.scalar(
        select(SalesRepresentativeCustomer).where(
            SalesRepresentativeCustomer.company_id == company_id,
            SalesRepresentativeCustomer.customer_source == source,
            SalesRepresentativeCustomer.customer_external_id == external_id,
        )
    )
    if assignment:
        assignment.sales_representative_id = representative.id
        assignment.active = True
        foreign_keys = customer_foreign_keys(source, external_id)
        assignment.customer_person_id = foreign_keys["customer_person_id"]
        assignment.customer_link_id = foreign_keys["customer_link_id"]
    else:
        db.add(
            SalesRepresentativeCustomer(
                company_id=company_id,
                sales_representative_id=representative.id,
                customer_source=source,
                customer_external_id=external_id,
                active=True,
                **customer_foreign_keys(source, external_id),
            )
        )
    db.commit()
    return list_sales_representative_customers(representative.id, request, db=db)


@app.delete(
    "/sales-representatives/{representative_id}/customers/{source}/{external_id}",
    tags=["Vendedores"],
)
def remove_sales_representative_customer(
    representative_id: int,
    source: str,
    external_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    company_id = active_company_id(request, db)
    assignment = db.scalar(
        select(SalesRepresentativeCustomer).where(
            SalesRepresentativeCustomer.company_id == company_id,
            SalesRepresentativeCustomer.sales_representative_id == representative_id,
            SalesRepresentativeCustomer.customer_source == source,
            SalesRepresentativeCustomer.customer_external_id == external_id,
            SalesRepresentativeCustomer.active == True,
        )
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="Vinculo nao encontrado")
    assignment.active = False
    db.commit()
    return {"ok": True}


@app.put(
    "/sales-representatives/{representative_id}/customers",
    response_model=SalesRepresentativeRead,
    tags=["Vendedores"],
)
def update_sales_representative_customers(
    representative_id: int,
    payload: SalesRepresentativeCustomersUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    representative = db.get(SalesRepresentative, representative_id)
    if not representative or representative.company_id != active_company_id(request, db):
        raise HTTPException(status_code=404, detail="Vendedor nao encontrado")
    replace_representative_customers(db, representative, payload.customer_ids)
    db.commit()
    return representative_to_read(db, representative)


@app.delete("/sales-representatives/{representative_id}", tags=["Vendedores"])
def delete_sales_representative(
    representative_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    representative = db.get(SalesRepresentative, representative_id)
    if not representative or representative.company_id != active_company_id(request, db):
        raise HTTPException(status_code=404, detail="Vendedor nao encontrado")
    linked_order = db.scalar(
        select(SalesOrder).where(SalesOrder.sales_representative_id == representative.id)
    )
    if linked_order:
        representative.active = False
    else:
        for assignment in db.scalars(
            select(SalesRepresentativeCustomer).where(
                SalesRepresentativeCustomer.sales_representative_id == representative.id
            )
        ).all():
            db.delete(assignment)
        db.flush()
        db.delete(representative)
    db.commit()
    return {"ok": True}


@app.put(
    "/customers/{source}/{external_id}/sales-representative",
    response_model=CustomerRead,
    tags=["Vendedores"],
)
def assign_customer_sales_representative(
    source: str,
    external_id: str,
    payload: SalesRepresentativeAssign,
    request: Request,
    db: Session = Depends(get_db),
):
    company_id = active_company_id(request, db)
    if not person_available_for_company(db, company_id, source, external_id):
        raise HTTPException(status_code=404, detail="Cliente nao encontrado na empresa ativa")
    current = db.scalar(
        select(SalesRepresentativeCustomer).where(
            SalesRepresentativeCustomer.company_id == company_id,
            SalesRepresentativeCustomer.customer_source == source,
            SalesRepresentativeCustomer.customer_external_id == external_id,
        )
    )
    if current:
        current.active = False
    if payload.sales_representative_id:
        representative = db.get(SalesRepresentative, payload.sales_representative_id)
        if not representative or representative.company_id != company_id or not representative.active:
            raise HTTPException(status_code=400, detail="Vendedor invalido")
        if current:
            current.sales_representative_id = representative.id
            current.active = True
            foreign_keys = customer_foreign_keys(source, external_id)
            current.customer_person_id = foreign_keys["customer_person_id"]
            current.customer_link_id = foreign_keys["customer_link_id"]
        else:
            db.add(
                SalesRepresentativeCustomer(
                    company_id=company_id,
                    sales_representative_id=representative.id,
                    customer_source=source,
                    customer_external_id=external_id,
                    active=True,
                    **customer_foreign_keys(source, external_id),
                )
            )
    db.commit()
    customer = next(
        (
            item
            for item in list_customers(request, db)
            if item["source"] == source and item["id"] == f"{source}:{external_id}"
        ),
        None,
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")
    return customer


@app.get(
    "/sales-representatives/whatsapp/{whatsapp_number}/context",
    response_model=SalesRepresentativeWhatsappContext,
    tags=["Vendedores"],
)
def sales_representative_whatsapp_context(
    whatsapp_number: str,
    request: Request,
    db: Session = Depends(get_db),
):
    phone = normalize_phone(whatsapp_number)
    representative = db.scalar(
        select(SalesRepresentative).where(
            SalesRepresentative.whatsapp_number == phone,
            SalesRepresentative.active == True,
        )
    )
    if not representative:
        raise HTTPException(status_code=404, detail="Vendedor nao identificado pelo WhatsApp")
    assignments = db.scalars(
        select(SalesRepresentativeCustomer).where(
            SalesRepresentativeCustomer.sales_representative_id == representative.id,
            SalesRepresentativeCustomer.active == True,
        )
    ).all()
    customers = []
    for assignment in assignments:
        customer = resolve_customer(
            db, f"{assignment.customer_source}:{assignment.customer_external_id}"
        )
        customers.append(
            {
                "id": f"{assignment.customer_source}:{assignment.customer_external_id}",
                "source": assignment.customer_source,
                "customer_profile_id": customer.get("profile_id"),
                "customer_profile_name": customer_profile_name(db, customer.get("profile_id")),
                "name": customer["name"],
                "active": True,
                "company_ids": [representative.company_id],
                "sales_representative_id": representative.id,
                "sales_representative_name": representative_to_read(db, representative)["user_name"],
            }
        )
    return {
        "sales_representative": representative_to_read(db, representative),
        "customers": customers,
    }


@app.post(
    "/assistant/whatsapp/messages",
    response_model=WhatsappAssistantResponse,
    tags=["Assistente WhatsApp"],
)
def process_whatsapp_order_message(
    payload: WhatsappAssistantMessage,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    phone = normalize_phone(payload.whatsapp_number)
    representative = db.scalar(
        select(SalesRepresentative).where(
            SalesRepresentative.whatsapp_number == phone,
            SalesRepresentative.active == True,
        )
    )
    if not representative:
        return {"reply": "Seu numero nao esta vinculado a um vendedor ativo no EasySales.", "state": "unauthorized"}
    settings_value = order_assistant_settings(db, representative.company_id)
    if not settings_value["enabled"]:
        return {
            "reply": "O Assistente de Pedidos via WhatsApp esta desativado para sua empresa.",
            "state": "disabled",
            "sales_representative_id": representative.id,
        }
    message_text = payload.text.strip()
    if payload.audio_base64:
        try:
            message_text = gemini_transcribe_audio(
                payload.audio_base64,
                payload.audio_mime_type,
                settings_value,
            )
        except RuntimeError as exc:
            return {
                "reply": str(exc),
                "state": "transcription_error",
                "sales_representative_id": representative.id,
            }
    if not message_text:
        return {
            "reply": "Envie o pedido por texto ou audio.",
            "state": "collecting",
            "sales_representative_id": representative.id,
        }
    now = datetime.utcnow()
    latest_session = db.scalar(
        select(WhatsappOrderSession)
        .where(
            WhatsappOrderSession.sales_representative_id == representative.id,
            WhatsappOrderSession.whatsapp_number == phone,
        )
        .order_by(WhatsappOrderSession.id.desc())
    )
    session = latest_session if latest_session and latest_session.state in {"collecting", "awaiting_confirmation"} else None
    if session and session.expires_at < now:
        session.state = "expired"
        db.commit()
        session = None
        expired_session = True
    else:
        expired_session = False
    normalized_message = normalize_search(message_text)
    session_timeout_minutes = assistant_session_timeout_minutes(settings_value)
    expires_at = now + timedelta(minutes=session_timeout_minutes)
    session_notice = assistant_session_notice(session_timeout_minutes)
    if normalized_message in ASSISTANT_CANCEL_COMMANDS:
        if session:
            session.state = "cancelled"
            session.draft = {}
            session.last_message = message_text
            session.expires_at = now
            db.commit()
        return {
            "reply": "Atendimento cancelado. Quando quiser recomecar, envie MENU.",
            "state": "cancelled",
            "sales_representative_id": representative.id,
        }
    if normalized_message in ASSISTANT_RESET_COMMANDS:
        save_assistant_module_session(db, representative, phone, None, message_text, expires_at, session)
        return {
            "reply": ASSISTANT_BOOT_MENU,
            "state": "routing",
            "sales_representative_id": representative.id,
        }
    selected_module = assistant_module_from_message(normalized_message)
    current_module = assistant_session_module(session)
    if selected_module:
        save_assistant_module_session(db, representative, phone, selected_module, message_text, expires_at, session)
        if selected_module == "bi":
            return {
                "reply": "BI selecionado. Envie sua pergunta sobre dashboards ou indicadores." + session_notice,
                "state": "bi_selected",
                "sales_representative_id": representative.id,
            }
        return {
            "reply": "EasySales selecionado. Pode pedir precos, catalogo ou enviar um pedido." + session_notice,
            "state": "sales_selected",
            "sales_representative_id": representative.id,
        }
    if current_module == "bi":
        return {
            "reply": "BI selecionado. Vou encaminhar sua pergunta para o assistente de BI. Para voltar ao menu, envie MENU.",
            "state": "bi_selected",
            "sales_representative_id": representative.id,
        }
    if current_module != "sales":
        save_assistant_module_session(db, representative, phone, None, message_text, expires_at, session)
        reply = ASSISTANT_BOOT_MENU
        if expired_session:
            reply = "A sessao anterior foi encerrada por inatividade.\n\n" + reply
        return {
            "reply": reply,
            "state": "routing",
            "sales_representative_id": representative.id,
        }
    if is_assistant_catalog_request(normalized_message):
        reply, recent_products = assistant_catalog(db, representative, settings_value, message_text)
        memory = assistant_session_memory(session)
        memory["selected_module"] = "sales"
        if recent_products:
            memory["recent_products"] = recent_products
            memory["last_intent"] = "catalog"
        remember_assistant_turn(memory, "user", message_text)
        remember_assistant_turn(memory, "assistant", reply)
        if session and session.state == "awaiting_confirmation":
            session.draft = memory
            session.last_message = message_text
            session.expires_at = expires_at
            db.commit()
        else:
            save_assistant_session_memory(db, representative, phone, memory, message_text, expires_at, session)
        return {
            "reply": reply + session_notice,
            "state": "catalog",
            "sales_representative_id": representative.id,
        }
    if session and session.state == "awaiting_confirmation":
        draft_update_error = None
        try:
            updated_draft, draft_changed = apply_assistant_draft_update(db, dict(session.draft or {}), message_text)
        except (HTTPException, ValueError, KeyError) as exc:
            updated_draft = session.draft
            draft_changed = False
            draft_update_error = exc.detail if isinstance(exc, HTTPException) else str(exc)
        if draft_changed and not assistant_requests_contextual_item_update(session.draft or {}, message_text):
            remember_assistant_turn(updated_draft, "user", message_text)
            if assistant_confirmation_requested(normalized_message):
                session.draft = updated_draft
                session.last_message = message_text
                session.expires_at = expires_at
                order = create_order_from_assistant(db, representative, session.draft)
                session.order_id = order.id
                session.state = "completed"
                db.commit()
                db.refresh(order)
                pdf_note = schedule_assistant_order_pdf(background_tasks, order, representative, settings_value)
                return {
                    "reply": f"Atualizei as condicoes e criei o pedido {order.order_number} como rascunho no EasySales. Total R$ {Decimal(order.total_amount):.2f}.{pdf_note}",
                    "state": "completed",
                    "sales_representative_id": representative.id,
                    "order_id": order.id,
                    "order_number": order.order_number,
                }
            summary = assistant_summary(updated_draft)
            remember_assistant_turn(updated_draft, "assistant", summary)
            session.draft = updated_draft
            session.last_message = message_text
            session.expires_at = expires_at
            db.commit()
            return {
                "reply": summary + session_notice,
                "state": "awaiting_confirmation",
                "sales_representative_id": representative.id,
            }
        if draft_update_error:
            memory = assistant_session_memory(session)
            remember_assistant_turn(memory, "user", message_text)
            reply = f"Nao consegui aplicar a alteracao: {draft_update_error}. O pedido atual foi mantido; envie a alteracao novamente."
            remember_assistant_turn(memory, "assistant", reply)
            session.draft = memory
            session.last_message = message_text
            session.expires_at = expires_at
            db.commit()
            return {
                "reply": reply + session_notice,
                "state": "awaiting_confirmation",
                "sales_representative_id": representative.id,
            }
        if (
            not assistant_requests_contextual_item_update(session.draft or {}, message_text)
            and (normalized_message in {"s", "ok"} or assistant_confirmation_requested(normalized_message))
        ):
            order = create_order_from_assistant(db, representative, session.draft)
            session.order_id = order.id
            session.state = "completed"
            db.commit()
            db.refresh(order)
            pdf_note = schedule_assistant_order_pdf(background_tasks, order, representative, settings_value)
            return {
                "reply": f"Pedido {order.order_number} criado como rascunho no EasySales. Total R$ {Decimal(order.total_amount):.2f}.{pdf_note}",
                "state": "completed",
                "sales_representative_id": representative.id,
                "order_id": order.id,
                "order_number": order.order_number,
            }
        try:
            memory = assistant_session_memory(session)
            contextual_message = assistant_draft_update_message(memory, message_text)
            updated_draft = build_assistant_draft(
                db,
                representative,
                contextual_message,
                settings_value,
                memory=memory,
            )
            updated_draft["selected_module"] = "sales"
            updated_draft["last_intent"] = "order_draft"
            updated_draft["recent_products"] = [
                {"id": item["product_id"], "sku": item["sku"], "name": item["name"]}
                for item in updated_draft["items"]
            ]
            updated_draft["conversation_history"] = assistant_conversation_history(memory)
            remember_assistant_turn(updated_draft, "user", message_text)
            summary = assistant_summary(updated_draft)
            remember_assistant_turn(updated_draft, "assistant", summary)
            session.draft = updated_draft
            session.last_message = message_text
            session.expires_at = expires_at
            if assistant_confirmation_requested(normalized_message):
                order = create_order_from_assistant(db, representative, session.draft)
                session.order_id = order.id
                session.state = "completed"
                db.commit()
                db.refresh(order)
                pdf_note = schedule_assistant_order_pdf(background_tasks, order, representative, settings_value)
                return {
                    "reply": f"Atualizei o pedido e criei {order.order_number} como rascunho no EasySales. Total R$ {Decimal(order.total_amount):.2f}.{pdf_note}",
                    "state": "completed",
                    "sales_representative_id": representative.id,
                    "order_id": order.id,
                    "order_number": order.order_number,
                }
            db.commit()
            return {
                "reply": summary + session_notice,
                "state": "awaiting_confirmation",
                "sales_representative_id": representative.id,
            }
        except (HTTPException, RuntimeError, ValueError, KeyError) as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            memory = assistant_session_memory(session)
            remember_assistant_turn(memory, "user", message_text)
            reply = f"Nao consegui entender a alteracao com seguranca: {detail}. O pedido atual foi mantido; pode explicar de outra forma."
            remember_assistant_turn(memory, "assistant", reply)
            session.draft = memory
            session.last_message = message_text
            session.expires_at = expires_at
            db.commit()
            return {
                "reply": reply + session_notice,
                "state": "awaiting_confirmation",
                "sales_representative_id": representative.id,
            }
    try:
        memory = assistant_session_memory(session)
        memory["recent_products"] = assistant_recent_products(memory)
        order_message = assistant_order_followup_message(memory, message_text)
        draft = build_assistant_draft(db, representative, order_message, settings_value, memory=memory)
    except (HTTPException, RuntimeError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        if is_assistant_incomplete_order_error(detail):
            memory = assistant_session_memory(session)
            memory["selected_module"] = "sales"
            memory["recent_products"] = assistant_recent_products(memory)
            memory["pending_order_message"] = assistant_order_followup_message(memory, message_text)
            memory["last_intent"] = "pending_order"
            remember_assistant_turn(memory, "user", message_text)
            remember_assistant_turn(memory, "assistant", detail)
            save_assistant_session_memory(db, representative, phone, memory, message_text, expires_at, session)
        return {
            "reply": detail,
            "state": "collecting",
            "sales_representative_id": representative.id,
        }
    draft_memory = assistant_session_memory(session)
    draft_memory.pop("pending_order_message", None)
    draft_memory["selected_module"] = "sales"
    draft_memory["last_intent"] = "order_draft"
    draft_memory["recent_products"] = [
        {"id": item["product_id"], "sku": item["sku"], "name": item["name"]}
        for item in draft["items"]
    ]
    remember_assistant_turn(draft_memory, "user", message_text)
    draft.update(draft_memory)
    remember_assistant_turn(draft, "assistant", assistant_summary(draft))
    session = WhatsappOrderSession(
        company_id=representative.company_id,
        sales_representative_id=representative.id,
        whatsapp_number=phone,
        state="awaiting_confirmation",
        draft=draft,
        last_message=message_text,
        expires_at=expires_at,
    )
    db.add(session)
    db.flush()
    close_other_assistant_sessions(db, representative, phone, session)
    if not settings_value.get("require_confirmation", True):
        order = create_order_from_assistant(db, representative, draft)
        session.order_id = order.id
        session.state = "completed"
        db.commit()
        db.refresh(order)
        pdf_note = schedule_assistant_order_pdf(background_tasks, order, representative, settings_value)
        return {
            "reply": f"Pedido {order.order_number} criado como rascunho no EasySales.{pdf_note}",
            "state": "completed",
            "sales_representative_id": representative.id,
            "order_id": order.id,
            "order_number": order.order_number,
        }
    db.commit()
    return {
        "reply": assistant_summary(draft) + session_notice,
        "state": "awaiting_confirmation",
        "sales_representative_id": representative.id,
    }


@app.get("/assistant/status", tags=["Assistente WhatsApp"])
def whatsapp_order_assistant_status(request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    settings_value = order_assistant_settings(db, company_id)
    rows = db.execute(
        text(
            """
            SELECT s.id, s.whatsapp_number, s.state, s.order_id, s.updated_at,
                   u.name AS sales_representative_name, o.order_number
            FROM sf_whatsapp_order_sessions s
            JOIN sf_sales_representatives sr ON sr.id = s.sales_representative_id
            JOIN users u ON u.id = sr.user_id
            LEFT JOIN sf_sales_orders o ON o.id = s.order_id
            WHERE s.company_id = :company_id
            ORDER BY s.id DESC
            LIMIT 20
            """
        ),
        {"company_id": company_id},
    ).mappings().all()
    return {
        "enabled": settings_value["enabled"],
        "provider": settings_value["provider"],
        "model": settings_value["model"],
        "require_confirmation": settings_value["require_confirmation"],
        "create_as_draft": settings_value["create_as_draft"],
        "send_order_pdf": settings_value["send_order_pdf"],
        "default_payment_days": settings_value["default_payment_days"],
        "price_table_id": settings_value["price_table_id"],
        "api_configured": bool(settings_value.get("api_key")),
        "sales_endpoint": "/assistant/whatsapp/messages",
        "n8n_webhook": settings_value.get("n8n_webhook_url"),
        "evolution_instance": settings_value.get("evolution_instance"),
        "sessions": [dict(row) for row in rows],
    }


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
            **customer_representative_fields(db, company_id, item.source, str(item.id)),
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
                    WHERE people.is_customer = TRUE AND people.active = TRUE
                    ORDER BY people.name ASC
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
                **customer_representative_fields(db, company_id, "easyfinance", str(row["id"])),
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
        **customer_representative_fields(db, company_id, item.source, str(item.id)),
    }


@app.put("/customers/{customer_id}", response_model=CustomerRead, tags=["Clientes"])
def update_customer(customer_id: int, payload: CustomerUpdate, request: Request, db: Session = Depends(get_db)):
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
        **customer_representative_fields(
            db, active_company_id(request, db), item.source, str(item.id)
        ),
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
    if Decimal(str(payload.suggested_margin_percent)) < 0:
        raise HTTPException(status_code=400, detail="Margem sugerida nao pode ser negativa")
    get_group_or_404(db, payload.product_group_id)
    get_class_or_404(db, payload.product_class_id)
    warehouse = resolve_warehouse(db, payload.default_warehouse_id)
    item = Product(
        product_group_id=payload.product_group_id,
        product_class_id=payload.product_class_id,
        sku=sku,
        name=payload.name.strip(),
        unit=payload.unit.strip().upper() or "UN",
        purchase_price=Decimal("0.00"),
        cost_price=Decimal("0.00"),
        suggested_margin_percent=payload.suggested_margin_percent,
        sale_price=Decimal("0.00"),
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
    if Decimal(str(payload.suggested_margin_percent)) < 0:
        raise HTTPException(status_code=400, detail="Margem sugerida nao pode ser negativa")
    get_group_or_404(db, payload.product_group_id)
    get_class_or_404(db, payload.product_class_id)
    warehouse = resolve_warehouse(db, payload.default_warehouse_id)
    item.product_group_id = payload.product_group_id
    item.product_class_id = payload.product_class_id
    item.sku = sku
    item.name = payload.name.strip()
    item.unit = payload.unit.strip().upper() or "UN"
    item.suggested_margin_percent = payload.suggested_margin_percent
    item.sale_price = suggested_sale_price(item.cost_price, payload.suggested_margin_percent)
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


@app.get("/reports/menu", tags=["Relatorios"])
def sales_reports_menu(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            """
            SELECT
                r.id,
                r.code,
                r.name,
                COALESCE(r.menu_label, r.name) AS menu_label,
                r.description,
                r.source_mode,
                COALESCE(r.print_scope, 'list') AS print_scope,
                r.target_screen,
                r.output_format,
                r.ordinal,
                r.show_in_menu,
                e.display_name AS entity_name,
                b.name AS browser_name
            FROM control_report_definitions r
            JOIN control_metadata_entities e ON e.id = r.entity_id
            LEFT JOIN control_browser_definitions b ON b.id = r.browser_id
            WHERE r.active = TRUE
              AND r.show_in_menu = TRUE
              AND r.target_app = 'easysales'
            ORDER BY r.ordinal ASC, COALESCE(r.menu_label, r.name) ASC
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


@app.get("/reports/available", tags=["Relatorios"])
def available_sales_reports(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            """
            SELECT
                r.id,
                r.code,
                r.name,
                COALESCE(r.menu_label, r.name) AS menu_label,
                r.description,
                r.source_mode,
                COALESCE(r.print_scope, 'list') AS print_scope,
                r.target_screen,
                r.output_format,
                r.ordinal,
                r.show_in_menu,
                e.display_name AS entity_name,
                b.name AS browser_name
            FROM control_report_definitions r
            JOIN control_metadata_entities e ON e.id = r.entity_id
            LEFT JOIN control_browser_definitions b ON b.id = r.browser_id
            WHERE r.active = TRUE
              AND r.target_app = 'easysales'
            ORDER BY r.target_screen ASC, r.ordinal ASC, COALESCE(r.menu_label, r.name) ASC
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


@app.get("/reports/{report_id}/print", tags=["Relatorios"])
def print_sales_list_report(report_id: int, target_screen: str, db: Session = Depends(get_db)):
    report = sales_screen_report(db, report_id, target_screen)
    if report.get("print_scope") != "list":
        raise HTTPException(status_code=400, detail="Este relatorio foi configurado para impressao individual.")
    content, content_type = render_sales_list_report(db, report)
    extension = "pdf" if (report.get("output_format") or "pdf") == "pdf" else "html"
    filename = f"{report['code']}.{extension}"
    return Response(
        content=content,
        media_type=content_type or ("application/pdf" if extension == "pdf" else "text/html"),
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/orders/{order_id}/print", tags=["Pedidos"])
def print_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    content, content_type = render_sales_order_pdf(db, order)
    filename = f"pedido-{order.order_number}.pdf"
    return Response(
        content=content,
        media_type=content_type or "application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/orders/{order_id}/reports/{report_id}/print", tags=["Pedidos"])
def print_order_report(order_id: int, report_id: int, request: Request, db: Session = Depends(get_db)):
    order = order_for_company_or_404(db, order_id, active_company_id(request, db))
    report = sales_screen_report(db, report_id, "orders")
    if report.get("print_scope") != "record":
        raise HTTPException(status_code=400, detail="Este relatorio foi configurado para impressao de lista.")
    content, content_type = render_sales_order_report(db, order, report)
    extension = "pdf" if (report.get("output_format") or "pdf") == "pdf" else "html"
    filename = f"{report['code']}-{order.order_number}.{extension}"
    return Response(
        content=content,
        media_type=content_type or ("application/pdf" if extension == "pdf" else "text/html"),
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.post("/orders", response_model=SalesOrderRead, status_code=status.HTTP_201_CREATED, tags=["Pedidos"])
def create_order(payload: SalesOrderCreate, request: Request, db: Session = Depends(get_db)):
    company_id = active_company_id(request, db)
    table = get_price_table_or_404(db, payload.price_table_id)
    if not table.active:
        raise HTTPException(status_code=400, detail="Tabela de preco inativa")
    customer = resolve_customer(db, payload.customer_id)
    if not person_available_for_company(db, company_id, customer["source"], customer["external_id"]):
        raise HTTPException(status_code=400, detail="Cliente nao vinculado a empresa ativa")
    representative = resolve_order_representative(
        db,
        company_id,
        customer["source"],
        customer["external_id"],
        payload.sales_representative_id,
    )
    order = SalesOrder(
        company_id=company_id,
        sales_representative_id=representative.id if representative else None,
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
    representative = resolve_order_representative(
        db,
        company_id,
        customer["source"],
        customer["external_id"],
        payload.sales_representative_id,
    )
    existing_items = db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id).order_by(SalesOrderItem.id.asc())).all()
    has_linked_items = any(linked_quantity_for_order_item(db, item.id) > 0 for item in existing_items)
    order.customer_source = customer["source"]
    order.sales_representative_id = representative.id if representative else None
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
    LoginRequest,
    LoginResponse,

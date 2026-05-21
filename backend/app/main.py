from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, engine, get_db
from app.models import (
    CustomerLink,
    CustomerProfile,
    PriceTable,
    PriceTableItem,
    Product,
    ProductClass,
    ProductGroup,
    SalesOrder,
    SalesOrderItem,
)
from app.schemas import (
    CustomerCreate,
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
    ProductRead,
    ProductUpdate,
    SalesOrderCreate,
    SalesOrderItemCreate,
    SalesOrderRead,
    SalesOrderUpdate,
)


settings = get_settings()
app = FastAPI(
    title="Forca de Vendas API",
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
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE sf_products ADD COLUMN IF NOT EXISTS purchase_price NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_products ADD COLUMN IF NOT EXISTS cost_price NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_customer_links ADD COLUMN IF NOT EXISTS customer_profile_id INTEGER"))
        connection.execute(text("ALTER TABLE people ADD COLUMN IF NOT EXISTS credit_limit NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS total_cost_amount NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS gross_profit_amount NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS profitability_percent NUMERIC(10, 4) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS approval_stage VARCHAR(30) NOT NULL DEFAULT 'draft'"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS approval_notes VARCHAR(800)"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS financial_approved_at TIMESTAMP"))
        connection.execute(text("ALTER TABLE sf_sales_orders ADD COLUMN IF NOT EXISTS commercial_approved_at TIMESTAMP"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS cost_unit_price NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS total_cost_amount NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS gross_profit_amount NUMERIC(14, 2) NOT NULL DEFAULT 0"))
        connection.execute(text("ALTER TABLE sf_sales_order_items ADD COLUMN IF NOT EXISTS profitability_percent NUMERIC(10, 4) NOT NULL DEFAULT 0"))
    seed_customer_profiles()


def normalize_code(value: str, field_name: str = "Codigo") -> str:
    code = value.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail=f"{field_name} e obrigatorio")
    return code


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
    }


def product_to_read(db: Session, item: Product) -> dict:
    group = db.get(ProductGroup, item.product_group_id) if item.product_group_id else None
    product_class = db.get(ProductClass, item.product_class_id) if item.product_class_id else None
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
        "description": item.description,
        "active": item.active,
    }


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


def price_table_item_to_read(db: Session, item: PriceTableItem) -> dict:
    product = db.get(Product, item.product_id)
    return {
        "id": item.id,
        "price_table_id": item.price_table_id,
        "product_id": item.product_id,
        "product_sku": product.sku if product else None,
        "product_name": product.name if product else None,
        "base_price": item.base_price,
        "active": item.active,
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


def order_to_read(db: Session, order: SalesOrder) -> dict:
    table = db.get(PriceTable, order.price_table_id)
    items = db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id).order_by(SalesOrderItem.id.asc())).all()
    return {
        "id": order.id,
        "order_number": order.order_number,
        "customer_source": order.customer_source,
        "customer_external_id": order.customer_external_id,
        "customer_name": order.customer_name,
        "price_table_id": order.price_table_id,
        "price_table_name": table.name if table else None,
        "order_date": order.order_date,
        "payment_due_date": order.payment_due_date,
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
        "items": items,
    }


def recalculate_order_totals(db: Session, order: SalesOrder):
    db.flush()
    items = db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id)).all()
    order.total_amount = money_round(sum((Decimal(str(row.total_amount)) for row in items), Decimal("0")))
    order.total_cost_amount = money_round(sum((Decimal(str(row.total_cost_amount)) for row in items), Decimal("0")))
    order.gross_profit_amount = money_round(order.total_amount - order.total_cost_amount)
    order.profitability_percent = weighted_order_profitability(items, order.total_amount)


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
    return len(notes) == 0, notes or ["Aprovacao financeira sem restricoes."]


def build_order_items(db: Session, order: SalesOrder, table: PriceTable, payload_items, payment_due_date: date):
    for payload_item in payload_items:
        if Decimal(str(payload_item.quantity)) <= 0:
            raise HTTPException(status_code=400, detail="Quantidade deve ser maior que zero")
        product = db.get(Product, payload_item.product_id)
        if not product or not product.active:
            raise HTTPException(status_code=400, detail="Produto inativo ou nao encontrado")
        price_item = db.scalar(
            select(PriceTableItem).where(
                PriceTableItem.price_table_id == table.id,
                PriceTableItem.product_id == product.id,
                PriceTableItem.active == True,
            )
        )
        if not price_item:
            raise HTTPException(status_code=400, detail=f"Produto {product.sku} sem preco ativo na tabela")
        unit_price = corrected_price(table, price_item.base_price, payment_due_date)
        item_total = money_round(Decimal(str(payload_item.quantity)) * unit_price)
        cost_unit_price = money_round(Decimal(str(product.cost_price or 0)))
        item_total_cost = money_round(Decimal(str(payload_item.quantity)) * cost_unit_price)
        item_profit = money_round(item_total - item_total_cost)
        item_profitability = profitability_percent(item_total, item_profit)
        db.add(
            SalesOrderItem(
                order_id=order.id,
                product_id=product.id,
                product_sku=product.sku,
                product_name=product.name,
                quantity=payload_item.quantity,
                base_unit_price=price_item.base_price,
                corrected_unit_price=unit_price,
                cost_unit_price=cost_unit_price,
                total_amount=item_total,
                total_cost_amount=item_total_cost,
                gross_profit_amount=item_profit,
                profitability_percent=item_profitability,
            )
        )


@app.get("/health", tags=["Sistema"])
def health():
    return {"ok": True, "service": "forca-vendas", "customer_provider": settings.customer_provider}


@app.get("/customers", response_model=list[CustomerRead], tags=["Clientes"])
def list_customers(db: Session = Depends(get_db)):
    local_links = db.scalars(
        select(CustomerLink).where(CustomerLink.source == "local", CustomerLink.active == True).order_by(CustomerLink.name.asc())
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
        }
        for item in local_links
    ]
    if settings.customer_provider == "easyfinance":
        try:
            rows = db.execute(
                text(
                    """
                    SELECT id, name, document_number, email, phone, city, state_code, active, credit_limit
                    FROM people
                    WHERE is_customer = TRUE AND active = TRUE
                    ORDER BY name ASC
                    """
                )
            ).mappings().all()
        except SQLAlchemyError:
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
            }
            for row in rows
        ]
        return [*shared_rows, *local_rows]

    return local_rows


@app.post("/customers", response_model=CustomerRead, status_code=status.HTTP_201_CREATED, tags=["Clientes"])
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
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
    }


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
    return db.scalars(select(CustomerProfile).order_by(CustomerProfile.code.asc(), CustomerProfile.name.asc())).all()


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
    db.commit()
    db.refresh(item)
    return item


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
    db.commit()
    db.refresh(item)
    return item


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
def assign_customer_profile(source: str, external_id: str, payload: CustomerProfileAssign, db: Session = Depends(get_db)):
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
    return next(row for row in list_customers(db) if row["id"] == f"{source}:{external_id}")


@app.get("/product-groups", response_model=list[ProductGroupRead], tags=["Produtos"])
def list_product_groups(db: Session = Depends(get_db)):
    return db.scalars(select(ProductGroup).order_by(ProductGroup.code.asc(), ProductGroup.name.asc())).all()


@app.post("/product-groups", response_model=ProductGroupRead, status_code=status.HTTP_201_CREATED, tags=["Produtos"])
def create_product_group(payload: ProductGroupCreate, db: Session = Depends(get_db)):
    code = normalize_code(payload.code)
    exists = db.scalar(select(ProductGroup).where(ProductGroup.code == code))
    if exists:
        raise HTTPException(status_code=400, detail="Codigo do grupo de produto ja cadastrado")
    item = ProductGroup(code=code, name=payload.name.strip(), description=payload.description, active=payload.active)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


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
    return item


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
def list_product_classes(db: Session = Depends(get_db)):
    items = db.scalars(select(ProductClass).order_by(ProductClass.code.asc(), ProductClass.name.asc())).all()
    return [class_to_read(db, item) for item in items]


@app.post("/product-classes", response_model=ProductClassRead, status_code=status.HTTP_201_CREATED, tags=["Produtos"])
def create_product_class(payload: ProductClassCreate, db: Session = Depends(get_db)):
    code = normalize_code(payload.code)
    exists = db.scalar(select(ProductClass).where(ProductClass.code == code))
    if exists:
        raise HTTPException(status_code=400, detail="Codigo da classe de produto ja cadastrado")
    get_group_or_404(db, payload.product_group_id)
    item = ProductClass(
        product_group_id=payload.product_group_id,
        code=code,
        name=payload.name.strip(),
        description=payload.description,
        active=payload.active,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return class_to_read(db, item)


@app.put("/product-classes/{class_id}", response_model=ProductClassRead, tags=["Produtos"])
def update_product_class(class_id: int, payload: ProductClassUpdate, db: Session = Depends(get_db)):
    item = db.get(ProductClass, class_id)
    if not item:
        raise HTTPException(status_code=404, detail="Classe de produto nao encontrada")
    code = normalize_code(payload.code)
    exists = db.scalar(select(ProductClass).where(ProductClass.code == code, ProductClass.id != class_id))
    if exists:
        raise HTTPException(status_code=400, detail="Codigo da classe de produto ja cadastrado")
    get_group_or_404(db, payload.product_group_id)
    item.product_group_id = payload.product_group_id
    item.code = code
    item.name = payload.name.strip()
    item.description = payload.description
    item.active = payload.active
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
def list_products(db: Session = Depends(get_db)):
    items = db.scalars(select(Product).order_by(Product.sku.asc(), Product.name.asc())).all()
    return [product_to_read(db, item) for item in items]


@app.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED, tags=["Produtos"])
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
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
    item = Product(
        product_group_id=payload.product_group_id,
        product_class_id=payload.product_class_id,
        sku=sku,
        name=payload.name.strip(),
        unit=payload.unit.strip().upper() or "UN",
        purchase_price=payload.purchase_price,
        cost_price=payload.cost_price,
        sale_price=payload.sale_price,
        description=payload.description,
        active=payload.active,
    )
    db.add(item)
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
    item.product_group_id = payload.product_group_id
    item.product_class_id = payload.product_class_id
    item.sku = sku
    item.name = payload.name.strip()
    item.unit = payload.unit.strip().upper() or "UN"
    item.purchase_price = payload.purchase_price
    item.cost_price = payload.cost_price
    item.sale_price = payload.sale_price
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


@app.get("/price-tables", response_model=list[PriceTableRead], tags=["Tabelas de preco"])
def list_price_tables(db: Session = Depends(get_db)):
    return db.scalars(select(PriceTable).order_by(PriceTable.code.asc(), PriceTable.name.asc())).all()


@app.post("/price-tables", response_model=PriceTableRead, status_code=status.HTTP_201_CREATED, tags=["Tabelas de preco"])
def create_price_table(payload: PriceTableCreate, db: Session = Depends(get_db)):
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
    db.commit()
    db.refresh(item)
    return item


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
    return item


@app.delete("/price-tables/{price_table_id}", tags=["Tabelas de preco"])
def delete_price_table(price_table_id: int, db: Session = Depends(get_db)):
    item = get_price_table_or_404(db, price_table_id)
    linked_order = db.scalar(select(SalesOrder).where(SalesOrder.price_table_id == price_table_id))
    if linked_order:
        raise HTTPException(status_code=400, detail="Tabela vinculada a pedidos")
    for table_item in db.scalars(select(PriceTableItem).where(PriceTableItem.price_table_id == price_table_id)).all():
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
    item = PriceTableItem(
        price_table_id=price_table_id,
        product_id=payload.product_id,
        base_price=payload.base_price,
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
    item.product_id = payload.product_id
    item.base_price = payload.base_price
    item.active = payload.active
    db.commit()
    db.refresh(item)
    return price_table_item_to_read(db, item)


@app.delete("/price-table-items/{item_id}", tags=["Tabelas de preco"])
def delete_price_table_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(PriceTableItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item da tabela de preco nao encontrado")
    db.delete(item)
    db.commit()
    return {"ok": True}


@app.get("/price-preview", response_model=PricePreviewRead, tags=["Tabelas de preco"])
def price_preview(price_table_id: int, product_id: int, payment_due_date: date, db: Session = Depends(get_db)):
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
    factor = correction_factor(table, payment_due_date)
    return {
        "price_table_id": price_table_id,
        "product_id": product_id,
        "base_price": item.base_price,
        "corrected_price": money_round(Decimal(str(item.base_price)) * factor),
        "correction_mode": table.correction_mode,
        "correction_factor": factor,
        "days": days,
    }


@app.get("/orders", response_model=list[SalesOrderRead], tags=["Pedidos"])
def list_orders(db: Session = Depends(get_db)):
    orders = db.scalars(select(SalesOrder).order_by(SalesOrder.id.desc())).all()
    return [order_to_read(db, order) for order in orders]


@app.get("/orders/{order_id}", response_model=SalesOrderRead, tags=["Pedidos"])
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.get(SalesOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")
    return order_to_read(db, order)


@app.post("/orders", response_model=SalesOrderRead, status_code=status.HTTP_201_CREATED, tags=["Pedidos"])
def create_order(payload: SalesOrderCreate, db: Session = Depends(get_db)):
    table = get_price_table_or_404(db, payload.price_table_id)
    if not table.active:
        raise HTTPException(status_code=400, detail="Tabela de preco inativa")
    customer = resolve_customer(db, payload.customer_id)
    order = SalesOrder(
        order_number=next_order_number(db),
        customer_source=customer["source"],
        customer_external_id=customer["external_id"],
        customer_name=customer["name"],
        price_table_id=table.id,
        order_date=payload.order_date,
        payment_due_date=payload.payment_due_date,
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
    build_order_items(db, order, table, payload.items, payload.payment_due_date)
    recalculate_order_totals(db, order)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.post("/orders/{order_id}/items", response_model=SalesOrderRead, status_code=status.HTTP_201_CREATED, tags=["Pedidos"])
def create_order_item(order_id: int, payload: SalesOrderItemCreate, db: Session = Depends(get_db)):
    order = db.get(SalesOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")
    table = get_price_table_or_404(db, order.price_table_id)
    build_order_items(db, order, table, [payload], order.payment_due_date)
    recalculate_order_totals(db, order)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.put("/orders/{order_id}/items/{item_id}", response_model=SalesOrderRead, tags=["Pedidos"])
def update_order_item(order_id: int, item_id: int, payload: SalesOrderItemCreate, db: Session = Depends(get_db)):
    order = db.get(SalesOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")
    item = db.get(SalesOrderItem, item_id)
    if not item or item.order_id != order.id:
        raise HTTPException(status_code=404, detail="Item do pedido nao encontrado")
    db.delete(item)
    db.flush()
    table = get_price_table_or_404(db, order.price_table_id)
    build_order_items(db, order, table, [payload], order.payment_due_date)
    recalculate_order_totals(db, order)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.delete("/orders/{order_id}/items/{item_id}", response_model=SalesOrderRead, tags=["Pedidos"])
def delete_order_item(order_id: int, item_id: int, db: Session = Depends(get_db)):
    order = db.get(SalesOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")
    item = db.get(SalesOrderItem, item_id)
    if not item or item.order_id != order.id:
        raise HTTPException(status_code=404, detail="Item do pedido nao encontrado")
    db.delete(item)
    db.flush()
    recalculate_order_totals(db, order)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.put("/orders/{order_id}", response_model=SalesOrderRead, tags=["Pedidos"])
def update_order(order_id: int, payload: SalesOrderUpdate, db: Session = Depends(get_db)):
    order = db.get(SalesOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")
    table = get_price_table_or_404(db, payload.price_table_id)
    if not table.active:
        raise HTTPException(status_code=400, detail="Tabela de preco inativa")
    customer = resolve_customer(db, payload.customer_id)
    for item in db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id)).all():
        db.delete(item)
    db.flush()
    order.customer_source = customer["source"]
    order.customer_external_id = customer["external_id"]
    order.customer_name = customer["name"]
    order.price_table_id = table.id
    order.order_date = payload.order_date
    order.payment_due_date = payload.payment_due_date
    order.status = "draft"
    order.approval_stage = "draft"
    order.approval_notes = None
    order.financial_approved_at = None
    order.commercial_approved_at = None
    order.notes = payload.notes
    build_order_items(db, order, table, payload.items, payload.payment_due_date)
    recalculate_order_totals(db, order)
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.post("/orders/{order_id}/submit", response_model=SalesOrderRead, tags=["Pedidos"])
def submit_order(order_id: int, db: Session = Depends(get_db)):
    order = db.get(SalesOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")
    recalculate_order_totals(db, order)
    if Decimal(str(order.total_amount or 0)) <= 0:
        raise HTTPException(status_code=400, detail="Pedido sem itens ou total zerado")
    order.status = "pending_financial"
    order.approval_stage = "financial"
    order.approval_notes = "Pedido enviado para aprovacao financeira."
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.post("/orders/{order_id}/approve-financial", response_model=SalesOrderRead, tags=["Pedidos"])
def approve_order_financial(order_id: int, db: Session = Depends(get_db)):
    order = db.get(SalesOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")
    recalculate_order_totals(db, order)
    allowed, notes = evaluate_financial_approval(db, order)
    order.approval_notes = " ".join(notes)
    if not allowed:
        order.status = "financial_blocked"
        order.approval_stage = "financial"
    else:
        order.status = "pending_commercial"
        order.approval_stage = "commercial"
        order.financial_approved_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.post("/orders/{order_id}/approve-commercial", response_model=SalesOrderRead, tags=["Pedidos"])
def approve_order_commercial(order_id: int, db: Session = Depends(get_db)):
    order = db.get(SalesOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")
    if order.status not in {"pending_commercial", "financial_blocked"}:
        raise HTTPException(status_code=400, detail="Pedido precisa passar pela aprovacao financeira")
    order.status = "approved"
    order.approval_stage = "approved"
    order.commercial_approved_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.post("/orders/{order_id}/reject", response_model=SalesOrderRead, tags=["Pedidos"])
def reject_order(order_id: int, db: Session = Depends(get_db)):
    order = db.get(SalesOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")
    order.status = "rejected"
    order.approval_stage = "rejected"
    order.approval_notes = "Pedido rejeitado."
    db.commit()
    db.refresh(order)
    return order_to_read(db, order)


@app.delete("/orders/{order_id}", tags=["Pedidos"])
def delete_order(order_id: int, db: Session = Depends(get_db)):
    order = db.get(SalesOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado")
    for item in db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id)).all():
        db.delete(item)
    db.delete(order)
    db.commit()
    return {"ok": True}

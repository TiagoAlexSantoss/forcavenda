from collections import Counter
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.integrations.schemas import (
    CatalogCustomerBatch,
    CatalogPriceTableBatch,
    CatalogProductBatch,
)
from app.models import CustomerLink, CustomerProfile, PriceTable, PriceTableItem, Product, ProductClass, ProductGroup


def normalize_code(value: str, label: str) -> str:
    code = value.strip().upper()
    if not code:
        raise HTTPException(status_code=422, detail=f"{label} deve ser informado")
    return code


def ensure_product_company(db: Session, company_id: int, product_id: int) -> None:
    db.execute(text("""
        INSERT INTO control_product_companies
            (company_id, product_source, product_external_id, active, created_at, updated_at)
        VALUES (:company_id, 'easysales', :product_id, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (product_source, product_external_id, company_id)
        DO UPDATE SET active = TRUE, updated_at = CURRENT_TIMESTAMP
    """), {"company_id": company_id, "product_id": str(product_id)})


def ensure_person_company(db: Session, company_id: int, source: str, external_id: str) -> None:
    db.execute(text("""
        INSERT INTO control_person_companies
            (company_id, person_source, person_external_id, active, created_at, updated_at)
        VALUES (:company_id, :source, :external_id, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (person_source, person_external_id, company_id)
        DO UPDATE SET active = TRUE, updated_at = CURRENT_TIMESTAMP
    """), {"company_id": company_id, "source": source, "external_id": external_id})


def ensure_catalog_company(db: Session, company_id: int, catalog_key: str, record_id: int) -> None:
    db.execute(text("""
        INSERT INTO control_catalog_companies
            (company_id, catalog_key, record_id, active, created_at, updated_at)
        VALUES (:company_id, :catalog_key, :record_id, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (catalog_key, record_id, company_id)
        DO UPDATE SET active = TRUE, updated_at = CURRENT_TIMESTAMP
    """), {"company_id": company_id, "catalog_key": catalog_key, "record_id": str(record_id)})


def upsert_products(db: Session, company_id: int, payload: CatalogProductBatch) -> dict:
    product_keys = [normalize_code(row.sku, "SKU") for row in payload.items]
    ensure_unique_keys(product_keys, "SKU")
    results = []
    for row in payload.items:
        sku = normalize_code(row.sku, "SKU")
        group = db.scalar(select(ProductGroup).where(ProductGroup.code == normalize_code(row.product_group_code, "Grupo"))) if row.product_group_code else None
        product_class = db.scalar(select(ProductClass).where(ProductClass.code == normalize_code(row.product_class_code, "Classe"))) if row.product_class_code else None
        if row.product_group_code and not group:
            raise HTTPException(status_code=422, detail=f"Grupo {row.product_group_code} nao encontrado para o produto {sku}")
        if row.product_class_code and not product_class:
            raise HTTPException(status_code=422, detail=f"Classe {row.product_class_code} nao encontrada para o produto {sku}")
        item = db.scalar(select(Product).where(Product.sku == sku))
        status = "updated" if item else "created"
        if not item:
            item = Product(sku=sku, name=row.name.strip())
            db.add(item)
        item.product_group_id = group.id if group else None
        item.product_class_id = product_class.id if product_class else None
        item.name = row.name.strip()
        item.unit = row.unit.strip().upper() or "UN"
        item.purchase_price = row.purchase_price
        item.cost_price = row.cost_price
        item.suggested_margin_percent = row.suggested_margin_percent
        item.sale_price = row.sale_price if row.sale_price is not None else (
            Decimal(str(row.cost_price)) * (Decimal("1") + Decimal(str(row.suggested_margin_percent)) / Decimal("100"))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        item.description = row.description
        item.active = row.active
        db.flush()
        ensure_product_company(db, company_id, item.id)
        results.append({"key": sku, "id": item.id, "status": status})
    db.commit()
    return batch_response(len(payload.items), results)


def export_products(db: Session, company_id: int, page: int, page_size: int, active_only: bool) -> dict:
    company_filter = text("""EXISTS (
        SELECT 1 FROM control_product_companies pc
        WHERE pc.company_id = :company_id
          AND pc.product_source = 'easysales'
          AND pc.product_external_id = CAST(sf_products.id AS VARCHAR)
          AND pc.active = TRUE
    )""")
    filters = [company_filter]
    if active_only:
        filters.append(Product.active == True)
    total = db.scalar(select(func.count(Product.id)).where(*filters).params(company_id=company_id)) or 0
    rows = db.execute(
        select(Product, ProductGroup.code.label("group_code"), ProductClass.code.label("class_code"))
        .outerjoin(ProductGroup, ProductGroup.id == Product.product_group_id)
        .outerjoin(ProductClass, ProductClass.id == Product.product_class_id)
        .where(*filters).params(company_id=company_id)
        .order_by(Product.sku.asc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [{
            "id": product.id, "sku": product.sku, "name": product.name, "unit": product.unit,
            "product_group_code": group_code, "product_class_code": class_code,
            "purchase_price": product.purchase_price, "cost_price": product.cost_price,
            "suggested_margin_percent": product.suggested_margin_percent, "sale_price": product.sale_price,
            "description": product.description, "active": product.active,
        } for product, group_code, class_code in rows],
    }


def upsert_customers(db: Session, company_id: int, payload: CatalogCustomerBatch) -> dict:
    customer_keys = [f"{row.source.strip().lower()}:{row.external_id.strip()}" for row in payload.items]
    ensure_unique_keys(customer_keys, "cliente")
    results = []
    for row in payload.items:
        source = row.source.strip().lower()
        if source in {"local", "easyfinance"}:
            raise HTTPException(
                status_code=422,
                detail=f"A origem {source} e reservada; use um identificador da integracao, como 'erp'",
            )
        external_id = row.external_id.strip()
        profile_code = normalize_code(row.customer_profile_code, "Perfil")
        profile = db.scalar(select(CustomerProfile).where(CustomerProfile.code == profile_code))
        if not profile:
            raise HTTPException(status_code=422, detail=f"Perfil comercial {profile_code} nao encontrado")
        item = db.scalar(select(CustomerLink).where(CustomerLink.source == source, CustomerLink.external_id == external_id))
        status = "updated" if item else "created"
        if not item:
            item = CustomerLink(source=source, external_id=external_id, name=row.name.strip())
            db.add(item)
        item.customer_profile_id = profile.id
        item.name = row.name.strip()
        item.document_number = row.document_number
        item.email = row.email
        item.phone = row.phone
        item.city = row.city
        item.state_code = row.state_code.upper() if row.state_code else None
        item.active = row.active
        db.flush()
        ensure_person_company(db, company_id, source, external_id)
        results.append({"key": f"{source}:{external_id}", "id": item.id, "status": status})
    db.commit()
    return batch_response(len(payload.items), results)


def upsert_price_tables(db: Session, company_id: int, payload: CatalogPriceTableBatch) -> dict:
    table_keys = [normalize_code(row.code, "Codigo da tabela") for row in payload.items]
    ensure_unique_keys(table_keys, "tabela de preco")
    results = []
    for row in payload.items:
        code = normalize_code(row.code, "Codigo da tabela")
        table = db.scalar(select(PriceTable).where(PriceTable.code == code))
        status = "updated" if table else "created"
        if not table:
            table = PriceTable(code=code, name=row.name.strip(), base_date=row.base_date)
            db.add(table)
        table.name = row.name.strip()
        table.correction_mode = row.correction_mode
        table.monthly_rate = row.monthly_rate
        table.base_date = row.base_date
        table.active = row.active
        db.flush()
        ensure_catalog_company(db, company_id, "sf_price_tables", table.id)
        for price in row.items:
            sku = normalize_code(price.product_sku, "SKU")
            product = db.scalar(select(Product).where(Product.sku == sku))
            if not product:
                raise HTTPException(status_code=422, detail=f"Produto {sku} nao encontrado para a tabela {code}")
            item = db.scalar(select(PriceTableItem).where(
                PriceTableItem.price_table_id == table.id,
                PriceTableItem.product_id == product.id,
            ))
            if not item:
                item = PriceTableItem(price_table_id=table.id, product_id=product.id)
                db.add(item)
            item.base_price = price.base_price
            item.margin_percent = price.margin_percent
            item.active = price.active
        results.append({"key": code, "id": table.id, "status": status})
    db.commit()
    return batch_response(len(payload.items), results)


def batch_response(received: int, results: list[dict]) -> dict:
    return {
        "received": received,
        "created": sum(result["status"] == "created" for result in results),
        "updated": sum(result["status"] == "updated" for result in results),
        "results": results,
    }


def ensure_unique_keys(keys: list[str], label: str) -> None:
    duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
    if duplicates:
        raise HTTPException(status_code=422, detail=f"{label} duplicado no lote: {', '.join(duplicates)}")

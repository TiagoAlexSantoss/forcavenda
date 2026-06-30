from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.integrations.catalog_service import export_products, upsert_customers, upsert_price_tables, upsert_products
from app.integrations.schemas import (
    CatalogBatchResponse,
    CatalogCustomerBatch,
    CatalogPriceTableBatch,
    CatalogProductBatch,
    CatalogProductExportPage,
)
from app.models import Company


bearer_auth = HTTPBearer(auto_error=False)
router = APIRouter(
    prefix="/integrations/catalog",
    tags=["Integracao de Catalogo"],
    dependencies=[Depends(bearer_auth)],
)


def integration_company_id(request: Request, db: Session) -> int:
    raw = request.headers.get("X-Company-Id") or request.query_params.get("company_id")
    company_id = int(raw) if raw else db.scalar(select(Company.id).where(Company.active == True).order_by(Company.id))
    company = db.get(Company, company_id) if company_id else None
    if not company or not company.active:
        raise HTTPException(status_code=400, detail="Empresa ativa invalida")
    allowed = getattr(request.state, "allowed_company_ids", None)
    if allowed is not None and company.id not in allowed:
        raise HTTPException(status_code=403, detail="Empresa nao liberada para o usuario")
    return company.id


@router.post(
    "/products",
    response_model=CatalogBatchResponse,
    summary="Receber ou atualizar produtos",
    description="Importacao idempotente em lote. O SKU identifica o produto para inclusao ou atualizacao.",
)
def import_products(payload: CatalogProductBatch, request: Request, db: Session = Depends(get_db)):
    return upsert_products(db, integration_company_id(request, db), payload)


@router.get(
    "/products",
    response_model=CatalogProductExportPage,
    summary="Enviar ou exportar produtos",
    description="Retorna o catalogo da empresa em paginas ordenadas por SKU.",
)
def send_products(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
    active_only: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return export_products(db, integration_company_id(request, db), page, page_size, active_only)


@router.post(
    "/customers",
    response_model=CatalogBatchResponse,
    summary="Receber ou atualizar clientes",
    description="Importacao idempotente em lote por origem e identificador externo.",
)
def import_customers(payload: CatalogCustomerBatch, request: Request, db: Session = Depends(get_db)):
    return upsert_customers(db, integration_company_id(request, db), payload)


@router.post(
    "/price-tables",
    response_model=CatalogBatchResponse,
    summary="Receber tabelas de preco",
    description="Importa cabecalhos e precos por SKU. Produtos devem ser enviados antes das tabelas.",
)
def import_price_tables(payload: CatalogPriceTableBatch, request: Request, db: Session = Depends(get_db)):
    return upsert_price_tables(db, integration_company_id(request, db), payload)

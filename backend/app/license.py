import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter

from app.config import get_settings


router = APIRouter(prefix="/license", tags=["Licenciamento"])
settings = get_settings()
CACHE_PATH = Path(__file__).resolve().parents[1] / ".license_cache.json"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def read_cache() -> dict | None:
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_cache(payload: dict) -> None:
    CACHE_PATH.write_text(
        json.dumps({**payload, "cached_at": utc_now().isoformat()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def cache_is_valid(cache: dict | None) -> bool:
    if not cache or not cache.get("valid") or not cache.get("cached_at"):
        return False
    try:
        cached_at = datetime.fromisoformat(cache["cached_at"])
    except ValueError:
        return False
    return cached_at + timedelta(days=settings.license_offline_grace_days) >= utc_now()


def configured() -> bool:
    return bool(settings.license_control_url and settings.license_tenant_id)


def validate_with_control() -> dict:
    if not configured():
        return {
            "valid": False,
            "status": "not_configured",
            "tenant_id": settings.license_tenant_id,
            "requested_module": settings.license_product,
            "message": "Licenciamento nao configurado neste ambiente",
        }
    payload = {
        "tenant_id": settings.license_tenant_id,
        "module": settings.license_product,
        "product": settings.license_product,
        "installation_id": settings.license_installation_id,
        "gateway_fingerprint": settings.license_gateway_fingerprint,
        "environment": settings.license_environment,
    }
    request = Request(
        f"{settings.license_control_url.rstrip('/')}/license/validate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        result = {"valid": False, "status": "control_http_error", "message": f"Control retornou HTTP {exc.code}"}
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        result = {"valid": False, "status": "control_unreachable", "message": str(exc)}
    if result.get("valid"):
        write_cache(result)
    return result


@router.post("/sync")
def sync_license():
    return {**validate_with_control(), "source": "control"}


@router.get("/local-status")
def local_license_status():
    cache = read_cache()
    if configured():
        result = validate_with_control()
        if result.get("valid"):
            return {**result, "source": "control"}
        if cache_is_valid(cache):
            return {**cache, "source": "cache", "status": "cached_active"}
        return {**result, "source": "control"}
    return {
        "valid": cache_is_valid(cache),
        "status": "cached_active" if cache_is_valid(cache) else "not_configured",
        "source": "cache" if cache else "local",
        "tenant_id": settings.license_tenant_id,
        "requested_module": settings.license_product,
        "message": "Configure LICENSE_CONTROL_URL e LICENSE_TENANT_ID para validar no Control",
    }

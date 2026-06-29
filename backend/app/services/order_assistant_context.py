import re
import unicodedata
from typing import Any


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
    "esse", "esses", "essas", "desses", "dessas", "este", "eles", "elas",
    "ambos", "ambas", "os dois", "as duas", "estes", "estas", "destes", "destas",
}


def normalize_context_text(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", ascii_value.lower())).strip()


def assistant_module_from_message(normalized_message: str) -> str | None:
    sales_choices = {"1", "sales", "easysales", "easy sales", "vendas", "pedido", "pedidos"}
    bi_choices = {"2", "bi", "portal bi", "dashboard", "dashboards", "indicador", "indicadores"}
    if normalized_message in sales_choices:
        return "sales"
    if normalized_message in bi_choices:
        return "bi"
    return None


def assistant_session_module(session: Any | None) -> str | None:
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


def assistant_session_memory(session: Any | None) -> dict:
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
        cleaned.append({
            "id": product_id,
            "sku": str(product.get("sku") or ""),
            "name": str(product.get("name") or ""),
        })
    return cleaned


def assistant_pending_order_message(memory: dict) -> str | None:
    value = memory.get("pending_order_message")
    return str(value).strip() if value else None


def is_assistant_incomplete_order_error(detail: str) -> bool:
    normalized = normalize_context_text(detail)
    return any(marker in normalized for marker in (
        "nao identifiquei com seguranca o cliente",
        "nao identifiquei produto ou quantidade",
        "nao encontrei produtos e quantidades",
    ))


def assistant_order_followup_message(memory: dict, message_text: str) -> str:
    pending = assistant_pending_order_message(memory)
    if not pending:
        return message_text
    normalized = normalize_context_text(message_text)
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

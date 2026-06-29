import re
import unicodedata
from decimal import Decimal
from difflib import SequenceMatcher

from fastapi import HTTPException

from app.services.order_assistant_context import ASSISTANT_RECENT_PRODUCT_REFERENCE_TERMS


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
        positions.extend((match.start(), match.end()) for match in re.finditer(re.escape(term), normalized_message))
    if not positions:
        return None
    longest_match_by_position = {}
    for index, end_index in positions:
        longest_match_by_position[index] = max(end_index, longest_match_by_position.get(index, end_index))
    for index, end_index in sorted(longest_match_by_position.items()):
        before = normalized_message[max(0, index - 50):index]
        matches = re.findall(r"\b(\d+(?:[,.]\d+)?)\b(?:\s+unidades?)?(?:\s+de)?\s*$", before)
        if matches:
            return Decimal(matches[-1].replace(",", "."))
        after = normalized_message[end_index:end_index + 30]
        matches = re.findall(
            r"^\s*(\d+(?:[,.]\d+)?)(?:\s+unidades?)?\b",
            after,
        )
        if matches:
            return Decimal(matches[0].replace(",", "."))
        matches = re.findall(r"\b(\d+(?:[,.]\d+)?)\b", before)
        if matches:
            return Decimal(matches[-1].replace(",", "."))
    return None

def assistant_shared_quantity(normalized_message: str) -> Decimal | None:
    patterns = [
        r"\b(\d+(?:[,.]\d+)?)\s+unidades?\s+de\s+cada\b",
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
    customer_name = customer["name"] if customer and customer_score >= 0.72 else None

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
        "customer": customer_name,
        "items": items,
        "payment_days": max(payment_terms) if payment_terms else None,
        "payment_terms": payment_terms,
        "delivery_date": None,
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
    payment_segments = re.findall(
        r"\b(?:pagamento(?:\s+(?:para|pra|em))?|prazo(?:\s+(?:para|pra|em))?|"
        r"condicoes?(?:\s+(?:para|pra|em))?|boleto(?:\s+(?:para|pra|em))?|para|pra|em)\s+"
        r"(\d{1,3}(?:\s+\d{1,3}){0,3})(?=\s*(?:dias?)?(?:\s|$))",
        normalized_message,
    )
    if payment_segments:
        terms.extend(int(value) for value in re.findall(r"\d{1,3}", payment_segments[-1]))
    for match in re.findall(r"\b\d{1,3}(?:\s*/\s*\d{1,3})+\b", normalized_message):
        terms.extend(int(value) for value in re.findall(r"\d{1,3}", match))
    if not terms and any(term in normalized_message for term in ["prazo", "pagamento", "condicao", "condicoes", "boleto", "faz em", "fazer em"]):
        payment_tail = re.search(
            r"\b(?:prazo|pagamento|condicoes?|boleto|faz em|fazer em)\b(.*)$",
            normalized_message,
        )
        if payment_tail:
            terms.extend(int(value) for value in re.findall(r"\b\d{1,3}\b", payment_tail.group(1)))
    if not terms and assistant_confirmation_requested(normalized_message):
        numbers = [int(value) for value in re.findall(r"\b\d{1,3}\b", normalized_message)]
        if len(numbers) > 1:
            terms.extend(numbers)
    return sorted({max(value, 0) for value in terms})

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


def assistant_quantity_correction(draft: dict, message_text: str) -> tuple[int, Decimal] | None:
    normalized = normalize_search(message_text)
    correction_markers = (
        "corrij", "alter", "ajust", "mude", "muda", "troque", "troca",
        "quantidade", "era", "deveria", "correto", "certo",
    )
    if not any(marker in normalized for marker in correction_markers):
        return None

    items = draft.get("items") or []
    mentioned_indexes = [
        index
        for index, item in enumerate(items)
        if assistant_product_mentioned(item, normalized)
    ]
    target_index = mentioned_indexes[0] if len(mentioned_indexes) == 1 else None
    if target_index is None:
        ordinal_terms = (
            (0, ("primeiro", "primeira", "1 item", "item 1", "produto 1")),
            (1, ("segundo", "segunda", "2 item", "item 2", "produto 2")),
            (2, ("terceiro", "terceira", "3 item", "item 3", "produto 3")),
            (3, ("quarto", "quarta", "4 item", "item 4", "produto 4")),
            (4, ("quinto", "quinta", "5 item", "item 5", "produto 5")),
            (5, ("sexto", "sexta", "6 item", "item 6", "produto 6")),
        )
        target_index = next(
            (index for index, terms in ordinal_terms if index < len(items) and any(term in normalized for term in terms)),
            None,
        )
        if target_index is None and any(term in normalized for term in ("ultimo", "ultima")) and items:
            target_index = len(items) - 1
    if target_index is None:
        return None

    positive_values = re.findall(
        r"(?<!nao )\b(?:para|pra|por|era|seja|ser|deveria ser|quantidade(?: e| era| deve ser)?|"
        r"correto e|certo e)\s+(?:de\s+)?(\d+(?:[,.]\d+)?)\b",
        normalized,
    )
    if positive_values:
        quantity = Decimal(positive_values[-1].replace(",", "."))
    else:
        negated_values = set(re.findall(r"\bnao\s+(?:era|e|ser)\s+(\d+(?:[,.]\d+)?)\b", normalized))
        values = [value for value in re.findall(r"\b\d+(?:[,.]\d+)?\b", normalized) if value not in negated_values]
        if len(values) != 1:
            return None
        quantity = Decimal(values[0].replace(",", "."))
    return (target_index, quantity) if quantity > 0 else None


def apply_assistant_quantity_correction(draft: dict, message_text: str) -> tuple[dict, bool]:
    correction = assistant_quantity_correction(draft, message_text)
    if not correction:
        return draft, False
    item_index, quantity = correction
    current_quantity = Decimal(str(draft["items"][item_index].get("quantity") or 0))
    if current_quantity == quantity:
        return draft, False
    draft["items"][item_index]["quantity"] = str(quantity)
    return draft, True


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
    changes_quantity = (
        item_mentioned
        and bool(re.search(r"\b\d+(?:[,.]\d+)?\b", normalized))
        and assistant_quantity_correction(draft, message_text) is None
    )
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


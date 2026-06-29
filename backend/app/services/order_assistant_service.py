from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SalesRepresentative, WhatsappOrderSession
from app.schemas import WhatsappAssistantMessage
from app.services.order_assistant_context import (
    ASSISTANT_BOOT_MENU,
    ASSISTANT_CANCEL_COMMANDS,
    ASSISTANT_RESET_COMMANDS,
    assistant_conversation_history,
    assistant_draft_update_message,
    assistant_module_from_message,
    assistant_order_followup_message,
    assistant_recent_products,
    assistant_session_memory,
    assistant_session_module,
    assistant_session_notice,
    assistant_session_timeout_minutes,
    is_assistant_incomplete_order_error,
    remember_assistant_turn,
)
from app.services.order_assistant_parser import (
    assistant_confirmation_requested,
    assistant_requests_contextual_item_update,
    assistant_summary,
    is_assistant_catalog_request,
    normalize_search,
)


@dataclass(frozen=True)
class OrderAssistantOperations:
    normalize_phone: Callable
    order_assistant_settings: Callable
    save_assistant_module_session: Callable
    assistant_catalog: Callable
    save_assistant_session_memory: Callable
    apply_assistant_draft_update: Callable
    create_order_from_assistant: Callable
    schedule_assistant_order_pdf: Callable
    build_assistant_draft: Callable
    close_other_assistant_sessions: Callable
    transcribe_audio: Callable


class OrderAssistantService:
    def __init__(self, operations: OrderAssistantOperations):
        self.operations = operations

    def process_message(
        self,
        payload: WhatsappAssistantMessage,
        background_tasks: BackgroundTasks,
        db: Session,
    ):
        phone = self.operations.normalize_phone(payload.whatsapp_number)
        representative = db.scalar(
            select(SalesRepresentative).where(
                SalesRepresentative.whatsapp_number == phone,
                SalesRepresentative.active == True,
            )
        )
        if not representative:
            return {"reply": "Seu numero nao esta vinculado a um vendedor ativo no EasySales.", "state": "unauthorized"}
        settings_value = self.operations.order_assistant_settings(db, representative.company_id)
        if not settings_value["enabled"]:
            return {
                "reply": "O Assistente de Pedidos via WhatsApp esta desativado para sua empresa.",
                "state": "disabled",
                "sales_representative_id": representative.id,
            }
        message_text = payload.text.strip()
        if payload.audio_base64:
            try:
                message_text = self.operations.transcribe_audio(
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
            session.draft = {}
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
            self.operations.save_assistant_module_session(db, representative, phone, None, message_text, expires_at, session)
            return {
                "reply": ASSISTANT_BOOT_MENU,
                "state": "routing",
                "sales_representative_id": representative.id,
            }
        selected_module = assistant_module_from_message(normalized_message)
        current_module = assistant_session_module(session)
        if selected_module:
            self.operations.save_assistant_module_session(db, representative, phone, selected_module, message_text, expires_at, session)
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
            self.operations.save_assistant_module_session(db, representative, phone, None, message_text, expires_at, session)
            reply = ASSISTANT_BOOT_MENU
            if expired_session:
                reply = "A sessao anterior foi encerrada por inatividade.\n\n" + reply
            return {
                "reply": reply,
                "state": "routing",
                "sales_representative_id": representative.id,
            }
        if is_assistant_catalog_request(normalized_message):
            reply, recent_products = self.operations.assistant_catalog(db, representative, settings_value, message_text)
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
                self.operations.save_assistant_session_memory(db, representative, phone, memory, message_text, expires_at, session)
            return {
                "reply": reply + session_notice,
                "state": "catalog",
                "sales_representative_id": representative.id,
            }
        if session and session.state == "awaiting_confirmation":
            draft_update_error = None
            try:
                updated_draft, draft_changed = self.operations.apply_assistant_draft_update(db, dict(session.draft or {}), message_text)
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
                    order = self.operations.create_order_from_assistant(db, representative, session.draft)
                    session.order_id = order.id
                    session.state = "completed"
                    db.commit()
                    db.refresh(order)
                    pdf_note = self.operations.schedule_assistant_order_pdf(background_tasks, order, representative, settings_value)
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
                order = self.operations.create_order_from_assistant(db, representative, session.draft)
                session.order_id = order.id
                session.state = "completed"
                db.commit()
                db.refresh(order)
                pdf_note = self.operations.schedule_assistant_order_pdf(background_tasks, order, representative, settings_value)
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
                updated_draft = self.operations.build_assistant_draft(
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
                    order = self.operations.create_order_from_assistant(db, representative, session.draft)
                    session.order_id = order.id
                    session.state = "completed"
                    db.commit()
                    db.refresh(order)
                    pdf_note = self.operations.schedule_assistant_order_pdf(background_tasks, order, representative, settings_value)
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
            draft = self.operations.build_assistant_draft(db, representative, order_message, settings_value, memory=memory)
        except (HTTPException, RuntimeError, ValueError) as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            memory = assistant_session_memory(session)
            memory["selected_module"] = "sales"
            memory["recent_products"] = assistant_recent_products(memory)
            if is_assistant_incomplete_order_error(detail):
                memory["pending_order_message"] = assistant_order_followup_message(memory, message_text)
                memory["last_intent"] = "pending_order"
            remember_assistant_turn(memory, "user", message_text)
            remember_assistant_turn(memory, "assistant", detail)
            self.operations.save_assistant_session_memory(db, representative, phone, memory, message_text, expires_at, session)
            return {
                "reply": detail + session_notice,
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
        self.operations.close_other_assistant_sessions(db, representative, phone, session)
        if not settings_value.get("require_confirmation", True):
            order = self.operations.create_order_from_assistant(db, representative, draft)
            session.order_id = order.id
            session.state = "completed"
            db.commit()
            db.refresh(order)
            pdf_note = self.operations.schedule_assistant_order_pdf(background_tasks, order, representative, settings_value)
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

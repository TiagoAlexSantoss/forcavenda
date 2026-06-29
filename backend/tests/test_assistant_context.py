import unittest

from app.services.order_assistant_context import (
    assistant_conversation_history,
    assistant_order_followup_message,
    assistant_session_timeout_minutes,
    remember_assistant_turn,
)
from app.services.order_assistant_parser import (
    apply_assistant_quantity_correction,
    assistant_requests_contextual_item_update,
    deterministic_assistant_extraction,
)


class AssistantContextTests(unittest.TestCase):
    customers = [{"id": "erp:1", "name": "Fazenda Boa Esperanca"}]
    products = [
        {"id": 1, "sku": "SIM-CALCI", "name": "Calcario agricola"},
        {"id": 2, "sku": "SIM-GLIFO", "name": "Herbicida glifosato"},
    ]

    def extract(self, message: str) -> dict:
        return deterministic_assistant_extraction(
            message,
            self.customers,
            self.products,
            self.products,
            {"default_payment_days": 30},
        )

    def assert_order(self, result: dict, quantities: list[int], payment_terms: list[int]) -> None:
        self.assertEqual(result["customer"], "Fazenda Boa Esperanca")
        self.assertEqual([float(item["quantity"]) for item in result["items"]], quantities)
        self.assertEqual(result["payment_terms"], payment_terms)

    def test_combines_recent_products_with_customer_followup(self):
        result = self.extract(
            "agora faca um pedido com esses produtos 10 unidades de cada\n"
            "Complemento do usuario: fazenda boa esperanca, pagamento para 30/60"
        )
        self.assert_order(result, [10, 10], [30, 60])

    def test_extracts_complete_order_without_ai(self):
        result = self.extract(
            "faca um pedido para fazenda boa esperanca, de 10 unidade de calcario e glifosato, para 30/60"
        )
        self.assert_order(result, [10, 10], [30, 60])

    def test_supports_quantity_after_each_product(self):
        result = self.extract(
            "pedido para fazenda boa esperanca: calcario 7 unidades e glifosato 8 unidades, pagamento em 30 dias"
        )
        self.assert_order(result, [7, 8], [30])

    def test_context_is_bounded_and_accumulates_incomplete_order(self):
        memory = {"pending_order_message": "pedido com esses produtos 10 unidades de cada"}
        combined = assistant_order_followup_message(memory, "fazenda boa esperanca para 30/60")
        self.assertIn("Complemento do usuario", combined)
        for index in range(20):
            remember_assistant_turn(memory, "user", f"mensagem {index}")
        history = assistant_conversation_history(memory)
        self.assertEqual(len(history), 12)
        self.assertEqual(history[0]["content"], "mensagem 8")

    def test_session_timeout_defaults_to_ten_minutes(self):
        self.assertEqual(assistant_session_timeout_minutes({}), 10)
        self.assertEqual(assistant_session_timeout_minutes({"session_timeout_minutes": 25}), 25)

    def test_corrects_named_product_and_preserves_other_items(self):
        draft = {
            "items": [
                {"sku": "SIM-ADJ", "name": "Adjuvante pulverizacao", "quantity": "100"},
                {"sku": "SIM-CALC", "name": "Calcario agricola", "quantity": "5"},
            ],
        }
        updated, changed = apply_assistant_quantity_correction(
            draft,
            "Nao, preciso que voce corrija o adjuvante. Era 10, nao era 100. O resto pode manter.",
        )
        self.assertTrue(changed)
        self.assertEqual([item["quantity"] for item in updated["items"]], ["10", "5"])
        self.assertFalse(assistant_requests_contextual_item_update(draft, "corrija o adjuvante, era 10 nao era 100"))

    def test_corrects_product_by_ordinal_position(self):
        draft = {
            "items": [
                {"sku": "SIM-ADJ", "name": "Adjuvante pulverizacao", "quantity": "100"},
                {"sku": "SIM-CALC", "name": "Calcario agricola", "quantity": "5"},
            ],
        }
        updated, changed = apply_assistant_quantity_correction(
            draft,
            "Corrija o primeiro produto para 10 e mantenha o restante igual.",
        )
        self.assertTrue(changed)
        self.assertEqual([item["quantity"] for item in updated["items"]], ["10", "5"])


if __name__ == "__main__":
    unittest.main()

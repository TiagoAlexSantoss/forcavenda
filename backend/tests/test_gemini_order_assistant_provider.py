import unittest
from unittest.mock import patch

from app.providers.gemini_order_assistant import GeminiOrderAssistantProvider


class GeminiOrderAssistantProviderTests(unittest.TestCase):
    def test_extract_order_uses_provider_boundary(self):
        provider = GeminiOrderAssistantProvider()
        response = {
            "candidates": [{
                "content": {"parts": [{"text": '{"customer":"Cliente A","items":[]}'}]},
            }],
        }
        with patch.object(provider, "_request", return_value=response) as request:
            result = provider.extract_order(
                "pedido para Cliente A",
                [{"id": 1, "name": "Cliente A"}],
                [{"id": 2, "sku": "P-1", "name": "Produto 1"}],
                {"api_key": "test-key", "model": "test-model"},
            )
        self.assertEqual(result["customer"], "Cliente A")
        request.assert_called_once()
        self.assertEqual(request.call_args.args[:2], ("test-key", "test-model"))

    def test_rejects_invalid_audio_before_network_call(self):
        provider = GeminiOrderAssistantProvider()
        with self.assertRaisesRegex(RuntimeError, "formato invalido"):
            provider.transcribe_audio("not-base64", "audio/ogg", {"api_key": "test-key"})


if __name__ == "__main__":
    unittest.main()

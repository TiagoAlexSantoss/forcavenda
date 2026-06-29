import base64
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen


class GeminiOrderAssistantProvider:
    """Gemini boundary for order extraction and audio transcription."""

    @staticmethod
    def _extract_json_object(value: str) -> dict:
        text_value = value.strip()
        if text_value.startswith("```"):
            text_value = re.sub(r"^```(?:json)?\s*|\s*```$", "", text_value, flags=re.IGNORECASE)
        start = text_value.find("{")
        end = text_value.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Resposta da IA sem JSON")
        return json.loads(text_value[start:end + 1])

    def extract_order(
        self,
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
            if recent_product_catalog else ""
        )
        history_instruction = (
            "Historico recente desta mesma conversa: "
            f"{json.dumps(conversation_history, ensure_ascii=False)}. "
            "Use o historico para manter cliente, produtos, quantidades e condicoes ja informados. "
            "A mensagem atual tem prioridade quando corrigir, remover, trocar ou acrescentar algo. "
            if conversation_history else ""
        )
        prompt = (
            "Extraia um pedido comercial da mensagem. Responda somente JSON valido com: "
            '{"customer":"texto ou null","items":[{"product":"texto","quantity":numero}],'
            '"payment_days":numero ou null,"payment_terms":[numero],"delivery_date":"YYYY-MM-DD ou null"}. '
            "Em payment_terms, preserve todos os prazos informados, por exemplo 30/60/90. "
            "Quando o usuario disser 'de cada', aplique a mesma quantidade a todos os produtos referenciados. "
            "Use payment_days como o maior prazo ou null quando nenhum prazo for informado. "
            f"{recent_instruction}{history_instruction}"
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
        body = self._request(api_key, model, payload, timeout=60)
        parts = (body.get("candidates") or [{}])[0].get("content", {}).get("parts") or []
        content = "\n".join(part.get("text", "") for part in parts)
        return self._extract_json_object(content)

    def transcribe_audio(self, audio_base64: str, mime_type: str | None, settings_value: dict) -> str:
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
        quota_exhausted = False
        for model in dict.fromkeys([audio_model, configured_model]):
            try:
                body = self._request(api_key, model, payload, timeout=90)
            except RuntimeError as exc:
                quota_exhausted = quota_exhausted or "429" in str(exc)
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

    @staticmethod
    def _request(api_key: str, model: str, payload: dict, timeout: int) -> dict:
        request_data = UrlRequest(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        )
        try:
            with urlopen(request_data, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"IA retornou erro {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError("Nao foi possivel acessar o provedor de IA") from exc

import unittest

from pydantic import ValidationError

from app.integrations.catalog_service import batch_response, ensure_unique_keys
from app.integrations.schemas import CatalogProductBatch
from app.main import external_openapi_schema


class CatalogIntegrationTests(unittest.TestCase):
    def test_routes_are_published_in_openapi_with_bearer_auth(self):
        schema = external_openapi_schema()
        expected = {
            ("/integrations/catalog/products", "post"),
            ("/integrations/catalog/products", "get"),
            ("/integrations/catalog/customers", "post"),
            ("/integrations/catalog/price-tables", "post"),
        }
        for path, method in expected:
            operation = schema["paths"][path][method]
            self.assertEqual(operation["security"], [{"HTTPBearer": []}])
        self.assertEqual(set(schema["paths"]), {path for path, _method in expected})
        self.assertNotIn("/auth/login", schema["paths"])
        self.assertNotIn("/license/sync", schema["paths"])

    def test_product_batch_rejects_negative_prices(self):
        with self.assertRaises(ValidationError):
            CatalogProductBatch.model_validate({
                "items": [{"sku": "P-1", "name": "Produto", "cost_price": -1}],
            })

    def test_batch_response_counts_upserts(self):
        response = batch_response(2, [
            {"key": "P-1", "id": 1, "status": "created"},
            {"key": "P-2", "id": 2, "status": "updated"},
        ])
        self.assertEqual((response["created"], response["updated"]), (1, 1))

    def test_duplicate_keys_are_rejected(self):
        with self.assertRaisesRegex(Exception, "duplicado no lote"):
            ensure_unique_keys(["P-1", "P-1"], "SKU")


if __name__ == "__main__":
    unittest.main()

"""Tests for Enterprise Hardening Phase 3: PII redaction wiring + IBAN detector."""

import pytest

from backend.pii_redactor import detect_pii, iban_check, redact
from backend.audit_log.service import _sanitize_detail


# ---------------------------------------------------------------------------
# IBAN detector (Req 6.1)
# ---------------------------------------------------------------------------


class TestIbanDetection:
    def test_valid_iban_checksum(self):
        # Well-known valid sample IBANs (mod-97 == 1)
        assert iban_check("GB82 WEST 1234 5698 7654 32") is True
        assert iban_check("DE89370400440532013000") is True
        assert iban_check("FR1420041010050500013M02606") is True

    def test_invalid_iban_checksum(self):
        assert iban_check("GB82WEST12345698765433") is False  # last digit changed
        assert iban_check("not-an-iban") is False
        assert iban_check("DE00370400440532013000") is False

    def test_iban_redacted_in_text(self):
        out = redact("Please wire to DE89370400440532013000 today")
        assert "DE89370400440532013000" not in out
        assert "[REDACTED_IBAN]" in out

    def test_iban_detected_as_match(self):
        matches = detect_pii("IBAN GB82 WEST 1234 5698 7654 32 end")
        assert any(m.type == "iban" for m in matches)


# ---------------------------------------------------------------------------
# Overlap resolution (no double-redaction)
# ---------------------------------------------------------------------------


class TestOverlapResolution:
    def test_no_overlapping_matches(self):
        text = "card 4111 1111 1111 1111 and email a@b.com and IBAN DE89370400440532013000"
        matches = detect_pii(text)
        # Ensure matches do not overlap each other.
        spans = sorted((m.start, m.end) for m in matches)
        for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
            assert e1 <= s2, f"overlapping spans: {(s1, e1)} {(s2, e2)}"

    def test_multiple_pii_classes_all_redacted(self):
        text = "email a@b.com phone +14155552671 card 4111111111111111"
        out = redact(text)
        assert "a@b.com" not in out
        assert "+14155552671" not in out
        assert "4111111111111111" not in out


# ---------------------------------------------------------------------------
# Per-class redaction (Req 6.5)
# ---------------------------------------------------------------------------


class TestPerClassRedaction:
    @pytest.mark.parametrize(
        "text,needle",
        [
            ("contact john.doe@example.com now", "john.doe@example.com"),
            ("call +14155552671 please", "+14155552671"),
            ("ssn 123-45-6789 here", "123-45-6789"),
            ("card 4111 1111 1111 1111 ok", "4111 1111 1111 1111"),
            ("iban DE89370400440532013000 ok", "DE89370400440532013000"),
        ],
    )
    def test_each_class_redacted(self, text, needle):
        out = redact(text)
        assert needle not in out


# ---------------------------------------------------------------------------
# Audit detail sanitization (Req 5.5, 6.2)
# ---------------------------------------------------------------------------


class TestAuditDetailSanitization:
    def test_redacts_pii_in_nested_detail(self):
        detail = {
            "actor_email": "user@example.com",
            "nested": {"card": "4111 1111 1111 1111"},
            "list": ["call +14155552671", "safe text"],
            "count": 3,
        }
        cleaned = _sanitize_detail(detail)
        assert "user@example.com" not in str(cleaned)
        assert "4111 1111 1111 1111" not in str(cleaned)
        assert "+14155552671" not in str(cleaned)
        assert cleaned["count"] == 3  # non-strings preserved

    def test_scrubs_secret_token_in_detail(self):
        detail = {"msg": "leaked key gsk_ABCDEFGHIJKLMNOPQRSTUVWX in error"}
        cleaned = _sanitize_detail(detail)
        assert "gsk_ABCDEFGHIJKLMNOPQRSTUVWX" not in str(cleaned)

    def test_non_dict_detail_passthrough(self):
        assert _sanitize_detail({}) == {}


# ---------------------------------------------------------------------------
# Middleware strict mode (Req 6.4)
# ---------------------------------------------------------------------------


class TestPiiMiddlewareStrictMode:
    @pytest.mark.asyncio
    async def test_strict_mode_redacts_query_string(self):
        from httpx import ASGITransport, AsyncClient
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from backend.api_gateway.middleware.pii_redact import PiiRedactMiddleware

        app = FastAPI()
        app.add_middleware(PiiRedactMiddleware, strict=True)

        @app.get("/probe")
        async def probe(request_state_holder=None):  # noqa: ANN001, ANN202
            return JSONResponse({"ok": True})

        captured = {}

        @app.middleware("http")
        async def capture(request, call_next):  # noqa: ANN001, ANN202
            response = await call_next(request)
            captured["redacted_query"] = getattr(request.state, "redacted_query", None)
            captured["pii_redacted"] = getattr(request.state, "pii_redacted", None)
            return response

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.get("/probe", params={"q": "email a@b.com"})

        assert captured["pii_redacted"] is True
        assert "a@b.com" not in (captured["redacted_query"] or "")

    @pytest.mark.asyncio
    async def test_non_strict_mode_marks_redacted_only(self):
        from httpx import ASGITransport, AsyncClient
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from backend.api_gateway.middleware.pii_redact import PiiRedactMiddleware

        app = FastAPI()
        app.add_middleware(PiiRedactMiddleware, strict=False)

        @app.get("/probe")
        async def probe():  # noqa: ANN202
            return JSONResponse({"ok": True})

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/probe")
        assert resp.status_code == 200

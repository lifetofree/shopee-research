"""Unit tests for the pure helpers in `scripts/capture_affiliate_traffic.py`.

Like `refresh_cookie.py`, the capture loop itself (launch Chromium, listen
for a human-driven search) isn't unit-testable without a real browser and a
logged-in account — this covers the host-filtering, body-truncation, and
entry-building logic that doesn't touch Playwright or the network.
"""

from __future__ import annotations

from capture_affiliate_traffic import MAX_BODY_BYTES, _is_target_host, _make_entry, _truncate_body


def test_is_target_host_matches_exact_host() -> None:
    assert _is_target_host("https://affiliate.shopee.co.th/graphql")


def test_is_target_host_matches_subdomain() -> None:
    assert _is_target_host("https://api.affiliate.shopee.co.th/v1/search")


def test_is_target_host_rejects_other_hosts() -> None:
    assert not _is_target_host("https://shopee.co.th/api/v4/search/search_items")
    assert not _is_target_host("https://cdn.example.com/affiliate.shopee.co.th")


def test_truncate_body_returns_unchanged_when_under_limit() -> None:
    text, truncated = _truncate_body("short body")
    assert text == "short body"
    assert truncated is False


def test_truncate_body_truncates_over_limit() -> None:
    long_text = "x" * (MAX_BODY_BYTES + 500)
    text, truncated = _truncate_body(long_text, max_bytes=MAX_BODY_BYTES)
    assert truncated is True
    assert len(text.encode("utf-8")) <= MAX_BODY_BYTES


def test_truncate_body_is_utf8_byte_safe() -> None:
    # Multi-byte chars near the cut point shouldn't raise or produce mojibake bytes.
    text = "ก" * 3000  # each char is 3 bytes in UTF-8 -> ~9000 bytes, over the 4096 cap
    result, truncated = _truncate_body(text, max_bytes=100)
    assert truncated is True
    assert len(result.encode("utf-8", errors="ignore")) <= 100


def test_make_entry_shape_matches_ticket_fields() -> None:
    entry = _make_entry(
        method="POST",
        url="https://affiliate.shopee.co.th/graphql",
        headers={"cookie": "SPC_AFF=x"},
        post_data='{"query": "..."}',
        status=200,
        response_headers={"content-type": "application/json"},
        response_body='{"data": {}}',
    )
    assert entry["method"] == "POST"
    assert entry["url"] == "https://affiliate.shopee.co.th/graphql"
    assert entry["headers"] == {"cookie": "SPC_AFF=x"}
    assert entry["post_data"] == '{"query": "..."}'
    assert entry["status"] == 200
    assert entry["response_headers"] == {"content-type": "application/json"}
    assert entry["response_body_truncated"] == '{"data": {}}'
    assert entry["truncated"] is False


def test_make_entry_flags_truncation() -> None:
    entry = _make_entry(
        method="GET",
        url="https://affiliate.shopee.co.th/api/x",
        headers={},
        post_data=None,
        status=200,
        response_headers={},
        response_body="y" * (MAX_BODY_BYTES + 1),
    )
    assert entry["truncated"] is True


def test_make_entry_handles_missing_response_body() -> None:
    entry = _make_entry(
        method="GET",
        url="https://affiliate.shopee.co.th/img.png",
        headers={},
        post_data=None,
        status=200,
        response_headers={},
        response_body=None,
    )
    assert entry["response_body_truncated"] == ""
    assert entry["truncated"] is False

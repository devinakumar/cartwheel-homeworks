"""Offline contracts for the HW1 additional read-only tool."""

from datetime import timedelta

import pytest

from agent import db
from agent.auth import AuthContext
from agent.tools import explain_refund_eligibility_logic


SHOPPER = AuthContext(user_id=1, role="shopper")


def test_explains_expired_window_without_writes(world):
    before = world["db"].read_bytes()
    result = explain_refund_eligibility_logic(SHOPPER, 3980)
    assert result["ok"] is True
    assert result["refund_eligible"] is False
    assert result["days_since_delivery"] == 45
    assert result["return_window_days"] == 30
    assert result["as_of"] == "2026-07-01"
    assert "outside the return window" in result["reason"]
    assert result["policy_ids"] == ["cw-returns"]
    assert world["db"].read_bytes() == before


def test_access_denial_exposes_no_order_or_policy_details(world, monkeypatch):
    from agent import tools

    def unexpected_policy_read():
        pytest.fail("policy must not be read for an unauthorized order")

    monkeypatch.setattr(tools, "load_policy_docs", unexpected_policy_read)
    for ctx in (
        AuthContext(user_id=2, role="shopper"),
        AuthContext(user_id=9002, role="merchant", store_id=2),
    ):
        result = explain_refund_eligibility_logic(ctx, 3980)
        assert set(result) == {"ok", "error", "reason"}
        assert result["error"] == "permission_denied"


@pytest.mark.parametrize("age,eligible", [(14, True), (15, False)])
def test_store_override_and_inclusive_boundary(world_copy, age, eligible):
    with db.connection() as conn:
        store_id = conn.execute(
            "SELECT id FROM stores WHERE slug = 'juniper-home-goods'"
        ).fetchone()["id"]
        delivered = db.world_asof(conn) - timedelta(days=age)
        conn.execute(
            "UPDATE orders SET store_id=?, delivered_at=?, refund_eligible=? WHERE id=4127",
            (store_id, delivered.isoformat(), eligible),
        )
        conn.commit()
    result = explain_refund_eligibility_logic(SHOPPER, 4127)
    assert result["ok"] is True
    assert result["refund_eligible"] is eligible
    assert result["return_window_days"] == 14
    assert "store-juniper-home-goods-policy" in result["policy_ids"]


@pytest.mark.parametrize(
    "change",
    ["refund_eligible=1", "delivered_at=NULL", "delivered_at='2099-01-01'"],
)
def test_inconsistent_data_requires_review(world_copy, change):
    with db.connection() as conn:
        conn.execute(f"UPDATE orders SET {change} WHERE id=3980")
        conn.commit()
    result = explain_refund_eligibility_logic(SHOPPER, 3980)
    assert result["ok"] is False
    assert result["error"] == "inconsistent_data"
    assert "human review" in result["reason"]


def test_missing_order_and_role_registration(world):
    from agent.agent import TOOLS_BY_ROLE

    assert explain_refund_eligibility_logic(SHOPPER, 999999)["error"] == "not_found"
    for role, user_id, store_id in (
        ("shopper", 1, None),
        ("merchant", 9001, 1),
        ("support", 9501, None),
    ):
        ctx = AuthContext(user_id=user_id, role=role, store_id=store_id)
        assert explain_refund_eligibility_logic(ctx, 4127)["refund_eligible"] is True
        assert "explain_refund_eligibility" in {tool.name for tool in TOOLS_BY_ROLE[role]}

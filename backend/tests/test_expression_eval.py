from __future__ import annotations

from a2ui_demo.flows.compiler import evaluate_expression


def test_simple_bool_true() -> None:
    assert evaluate_expression("attrs.has_ms_credit_card == true", {"has_ms_credit_card": True}) is True


def test_simple_bool_false() -> None:
    assert evaluate_expression("attrs.has_ms_credit_card == true", {"has_ms_credit_card": False}) is False


def test_negation() -> None:
    assert evaluate_expression("attrs.is_sams_member == false", {"is_sams_member": False}) is True


def test_numeric_gte() -> None:
    assert evaluate_expression("attrs.age >= 18", {"age": 30}) is True
    assert evaluate_expression("attrs.age >= 18", {"age": 16}) is False


def test_and_operator() -> None:
    attrs = {"age": 25, "is_sams_member": False}
    assert evaluate_expression("attrs.age >= 18 && attrs.is_sams_member == false", attrs) is True


def test_or_operator() -> None:
    attrs = {"has_ms_credit_card": True, "is_sams_member": False}
    assert evaluate_expression("attrs.has_ms_credit_card == true || attrs.is_sams_member == true", attrs) is True


def test_not_operator() -> None:
    assert evaluate_expression("!attrs.is_sams_member", {"is_sams_member": False}) is True
    assert evaluate_expression("!attrs.is_sams_member", {"is_sams_member": True}) is False


def test_empty_expression_returns_false() -> None:
    assert evaluate_expression("", {}) is False
    assert evaluate_expression("   ", {}) is False


def test_missing_attr_returns_none_comparison() -> None:
    assert evaluate_expression("attrs.nonexistent == true", {}) is False


def test_string_equality() -> None:
    assert evaluate_expression("attrs.userId == 'U1001'", {"userId": "U1001"}) is True
    assert evaluate_expression("attrs.userId == 'U1001'", {"userId": "U1002"}) is False

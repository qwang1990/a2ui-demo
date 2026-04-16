from __future__ import annotations

from a2ui_demo.abox_store import abox_list, abox_query


def test_abox_list_returns_all_applicant_users() -> None:
    instances = abox_list("ApplicantUser")
    assert len(instances) >= 5
    names = [i["fullName"] for i in instances]
    assert "张三" in names
    assert "李四" in names
    assert "王五" in names


def test_abox_list_unknown_type_returns_empty() -> None:
    assert abox_list("UnknownType") == []


def test_abox_query_by_fullname() -> None:
    matches = abox_query("ApplicantUser", {"fullName": "张三"})
    assert len(matches) == 1
    assert matches[0]["userId"] == "U1001"


def test_abox_query_by_fullname_and_id() -> None:
    matches = abox_query("ApplicantUser", {"fullName": "李四", "idNumber": "11010119900101SAMS_MEMBER234"})
    assert len(matches) == 1
    assert matches[0]["is_sams_member"] is True


def test_abox_query_with_return_keys() -> None:
    matches = abox_query("ApplicantUser", {"fullName": "王五"}, return_keys=["userId", "has_ms_credit_card"])
    assert len(matches) == 1
    assert set(matches[0].keys()) == {"userId", "has_ms_credit_card"}
    assert matches[0]["has_ms_credit_card"] is True


def test_abox_query_no_match() -> None:
    matches = abox_query("ApplicantUser", {"fullName": "不存在的人"})
    assert matches == []


def test_abox_query_case_insensitive() -> None:
    matches = abox_query("ApplicantUser", {"fullName": "张三"})
    assert len(matches) == 1

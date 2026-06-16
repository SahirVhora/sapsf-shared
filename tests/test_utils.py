"""Tests for sapsf_shared.utils."""

import json
from datetime import UTC, date, datetime

from sapsf_shared.utils import (
    build_odata_filter,
    flatten_record,
    is_active_today,
    odata_escape,
    parse_sf_date,
)


class TestOdataEscape:
    def test_plain_value_unchanged(self):
        assert odata_escape("IT") == "IT"

    def test_single_quote_doubled(self):
        assert odata_escape("O'Brien") == "O''Brien"

    def test_injection_attempt_is_neutralised(self):
        # An attacker-style value must not be able to close the literal.
        raw = "x' or externalCode ne 'y"
        escaped = odata_escape(raw)
        assert "''" in escaped
        # Rebuilt literal contains no unescaped quote that ends the string early.
        literal = f"externalCode eq '{escaped}'"
        assert literal == "externalCode eq 'x'' or externalCode ne ''y'"

    def test_non_string_coerced(self):
        assert odata_escape(123) == "123"

    def test_build_odata_filter_escapes(self):
        result = build_odata_filter({"name": "O'Brien"})
        assert result == "name eq 'O''Brien'"


class TestParseSfDate:
    def test_epoch_date(self):
        ts_ms = int(datetime(2024, 1, 15, tzinfo=UTC).timestamp() * 1000)
        result = parse_sf_date(f"/Date({ts_ms})/")
        assert result == date(2024, 1, 15)

    def test_iso_datetime(self):
        assert parse_sf_date("2024-01-15T10:30:00") == date(2024, 1, 15)

    def test_iso_datetime_with_z(self):
        assert parse_sf_date("2024-01-15T10:30:00Z") == date(2024, 1, 15)

    def test_date_only(self):
        assert parse_sf_date("2024-01-15") == date(2024, 1, 15)

    def test_invalid_date(self):
        assert parse_sf_date("not-a-date") is None

    def test_none(self):
        assert parse_sf_date(None) is None

    def test_empty_string(self):
        assert parse_sf_date("  ") is None


class TestIsActiveToday:
    def test_active_no_dates(self):
        assert is_active_today({"status": "A"}) is True

    def test_inactive_by_status(self):
        assert is_active_today({"status": "I"}) is False
        assert is_active_today({"cust_status": "Terminated"}) is False

    def test_future_start_date(self):
        future = date.today().replace(year=date.today().year + 1)
        item = {"startDate": future.isoformat()}
        assert is_active_today(item) is False

    def test_past_end_date(self):
        past = date.today().replace(year=date.today().year - 1)
        item = {"endDate": past.isoformat()}
        assert is_active_today(item) is False

    def test_active_with_dates(self):
        today = date.today()
        past = today.replace(year=today.year - 1)
        future = today.replace(year=today.year + 1)
        item = {"startDate": past.isoformat(), "endDate": future.isoformat()}
        assert is_active_today(item) is True

    def test_no_status_no_dates(self):
        assert is_active_today({}) is True


class TestFlattenRecord:
    def test_flatten_simple(self):
        record = {"userId": "1", "firstName": "Alice"}
        result = flatten_record(record)
        assert result == {"userId": "1", "firstName": "Alice"}

    def test_skip_metadata(self):
        record = {"__metadata": {"uri": "..."}, "userId": "1"}
        result = flatten_record(record)
        assert "__metadata" not in result
        assert result["userId"] == "1"

    def test_skip_deferred(self):
        record = {"nav": {"__deferred": {"uri": "..."}}, "userId": "1"}
        result = flatten_record(record)
        assert "nav" not in result

    def test_inline_single_object(self):
        record = {"manager": {"userId": "2", "firstName": "Bob"}, "userId": "1"}
        result = flatten_record(record)
        assert result["manager_userId"] == "2"
        assert result["manager_firstName"] == "Bob"

    def test_serialize_results(self):
        record = {"children": {"results": [{"id": "c1"}]}}
        result = flatten_record(record)
        assert json.loads(result["children"]) == [{"id": "c1"}]

    def test_serialize_list(self):
        record = {"tags": ["a", "b"]}
        result = flatten_record(record)
        assert json.loads(result["tags"]) == ["a", "b"]

    def test_datetime_to_iso(self):
        dt = datetime(2024, 1, 15, 10, 30, tzinfo=UTC)
        record = {"created": dt}
        result = flatten_record(record)
        assert result["created"] == dt.isoformat()


class TestBuildODataFilter:
    def test_single_filter(self):
        result = build_odata_filter({"status": "A"})
        assert result == "status eq 'A'"

    def test_multiple_filters(self):
        result = build_odata_filter({"status": "A", "country": "GBR"})
        assert "status eq 'A'" in result
        assert "country eq 'GBR'" in result

    def test_numeric_value(self):
        result = build_odata_filter({"age": 30})
        assert result == "age eq 30"

    def test_custom_combiner(self):
        result = build_odata_filter({"a": "1", "b": "2"}, combiner="or")
        assert "or" in result

    def test_custom_operator(self):
        result = build_odata_filter({"age": 18}, operator="ge")
        assert result == "age ge 18"

    def test_empty_returns_none(self):
        assert build_odata_filter({}) is None

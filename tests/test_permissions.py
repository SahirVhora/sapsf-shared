"""Tests for sapsf_shared.permissions module.

Covers:
- XML parsing for all RBP function responses
- Batch handling (>100 users/roles)
- Edge cases: empty XML, malformed XML, no roles, no users
- Risk flagging logic
- Excel export (basic smoke)
- Full scan orchestration with mock client
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sapsf_shared.permissions import (
    PermissionAnalyzer,
    PermissionCatalogue,
    PermissionRole,
    PermissionScanReport,
    UserRoleAssignment,
    _parse_permission_metadata_xml,
    _parse_role_permissions_regex,
    _parse_role_permissions_xml,
    _parse_user_roles_regex,
    _parse_user_roles_xml,
    _parse_users_permissions_xml,
)

# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_client():
    """Create a mock SFClient that returns canned responses."""
    client = MagicMock()
    client.base_url = "https://api4.sapsf.com/odata/v2"
    # Mock _request_with_retry to return response-like objects
    return client


def _mock_response(text: str, status_code: int = 200):
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    resp.json.return_value = json.loads(text) if text.startswith(("{", "[")) else {}
    return resp


# ═══════════════════════════════════════════════════════════════════════════
# XML Parsing Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestParseRolePermissionsXML:
    """Tests for _parse_role_permissions_xml."""

    def test_standard_xml(self):
        xml = """<?xml version="1.0"?>
<rolePermissions>
    <role>
        <roleId>1001</roleId>
        <roleName>HR Manager</roleName>
        <permissions>
            <permission>VIEW_EMPLOYEE_DATA</permission>
            <permission>MANAGE_COMPENSATION</permission>
            <permission>VIEW_PERSONAL_INFO</permission>
        </permissions>
    </role>
    <role>
        <roleId>1002</roleId>
        <roleName>Recruiter</roleName>
        <permissions>
            <permission>MANAGE_RECRUITING</permission>
            <permission>VIEW_JOB_REQUISITIONS</permission>
        </permissions>
    </role>
</rolePermissions>"""
        result = _parse_role_permissions_xml(xml)
        assert "HR Manager" in result
        assert "VIEW_EMPLOYEE_DATA" in result["HR Manager"]
        assert "MANAGE_COMPENSATION" in result["HR Manager"]
        assert "Recruiter" in result
        assert "MANAGE_RECRUITING" in result["Recruiter"]

    def test_role_with_no_permissions(self):
        xml = """<?xml version="1.0"?>
<rolePermissions>
    <role>
        <roleId>2001</roleId>
        <roleName>Empty Role</roleName>
        <permissions/>
    </role>
</rolePermissions>"""
        result = _parse_role_permissions_xml(xml)
        assert "Empty Role" in result
        assert result["Empty Role"] == []

    def test_empty_xml(self):
        result = _parse_role_permissions_xml("")
        assert result == {}

    def test_malformed_xml_fallback_to_regex(self):
        """When XML parsing fails, should fall back to regex parser."""
        xml = """<rolePermissions>
<role>
<roleName>HR_MGR</roleName>
<permissions>
<permission>P1</permission>
<permission>P2</permission>
</permissions>
</role>
</rolePermissions>"""
        result = _parse_role_permissions_xml(xml)
        # Should work with either parser
        assert "HR_MGR" in result
        assert "P1" in result["HR_MGR"]

    def test_namespaced_xml(self):
        """XML with namespaces should still parse."""
        xml = """<?xml version="1.0"?>
<ns:rolePermissions xmlns:ns="http://sap.com/sf/rbp">
    <ns:role>
        <ns:roleId>101</ns:roleId>
        <ns:roleName>Admin</ns:roleName>
        <ns:permissions>
            <ns:permission>FULL_ACCESS</ns:permission>
        </ns:permissions>
    </ns:role>
</ns:rolePermissions>"""
        result = _parse_role_permissions_xml(xml)
        assert "Admin" in result
        assert "FULL_ACCESS" in result["Admin"]

    def test_role_with_numeric_only_id(self):
        """When roleId is present but roleName is empty, use roleId as key."""
        xml = """<?xml version="1.0"?>
<rolePermissions>
    <role>
        <roleId>9999</roleId>
        <roleName></roleName>
        <permissions>
            <permission>API_ACCESS</permission>
        </permissions>
    </role>
</rolePermissions>"""
        result = _parse_role_permissions_xml(xml)
        # Should have the entry, but with empty roleName
        assert any("API_ACCESS" in v for v in result.values())


class TestParseUserRolesXML:
    """Tests for _parse_user_roles_xml."""

    def test_standard_xml(self):
        xml = """<?xml version="1.0"?>
<userRolesReport>
    <userRole>
        <userName>john.doe</userName>
        <roles>
            <role>HR Manager</role>
            <role>Payroll Admin</role>
        </roles>
    </userRole>
    <userRole>
        <userName>jane.smith</userName>
        <roles>
            <role>Recruiter</role>
        </roles>
    </userRole>
</userRolesReport>"""
        result = _parse_user_roles_xml(xml)
        assert "john.doe" in result
        assert "HR Manager" in result["john.doe"]
        assert "Payroll Admin" in result["john.doe"]
        assert "jane.smith" in result
        assert "Recruiter" in result["jane.smith"]

    def test_user_with_no_roles(self):
        xml = """<?xml version="1.0"?>
<userRolesReport>
    <userRole>
        <userName>unassigned.user</userName>
        <roles/>
    </userRole>
</userRolesReport>"""
        result = _parse_user_roles_xml(xml)
        assert "unassigned.user" in result
        assert result["unassigned.user"] == []

    def test_empty_xml(self):
        result = _parse_user_roles_xml("")
        assert result == {}

    def test_regex_fallback(self):
        xml = """<userRolesReport>
<userRole>
<userName>test.user</userName>
<roles>
<role>Role A</role>
<role>Role B</role>
</roles>
</userRole>
</userRolesReport>"""
        result = _parse_user_roles_xml(xml)
        assert "test.user" in result
        assert "Role A" in result["test.user"]

    def test_multiple_users_same_roles(self):
        xml = """<?xml version="1.0"?>
<userRolesReport>
    <userRole>
        <userName>user1</userName>
        <roles><role>Everyone</role></roles>
    </userRole>
    <userRole>
        <userName>user2</userName>
        <roles><role>Everyone</role></roles>
    </userRole>
    <userRole>
        <userName>user3</userName>
        <roles><role>Everyone</role></roles>
    </userRole>
</userRolesReport>"""
        result = _parse_user_roles_xml(xml)
        assert len(result) == 3
        for username in ("user1", "user2", "user3"):
            assert result[username] == ["Everyone"]


class TestParseUsersPermissionsXML:
    """Tests for _parse_users_permissions_xml."""

    def test_standard_xml(self):
        xml = """<?xml version="1.0"?>
<usersPermissions>
    <userPermission>
        <userName>john.doe</userName>
        <permissions>
            <permission>VIEW_EMPLOYEE_DATA</permission>
            <permission>MANAGE_COMPENSATION</permission>
        </permissions>
    </userPermission>
</usersPermissions>"""
        result = _parse_users_permissions_xml(xml)
        assert "john.doe" in result
        assert "VIEW_EMPLOYEE_DATA" in result["john.doe"]

    def test_empty_xml(self):
        result = _parse_users_permissions_xml("")
        assert result == {}


class TestParsePermissionMetadataXML:
    """Tests for _parse_permission_metadata_xml."""

    def test_standard_xml(self):
        xml = """<?xml version="1.0"?>
<permissionMetadata>
    <category name="Employee Data">
        <permission>
            <code>VIEW_EMPLOYEE_DATA</code>
            <label>View Employee Data</label>
        </permission>
        <permission>
            <code>MANAGE_EMPLOYEE_DATA</code>
            <label>Manage Employee Data</label>
        </permission>
    </category>
    <category name="Compensation">
        <permission>
            <code>VIEW_COMPENSATION</code>
            <label>View Compensation Info</label>
        </permission>
    </category>
</permissionMetadata>"""
        result = _parse_permission_metadata_xml(xml)
        assert "Employee Data" in result
        assert len(result["Employee Data"]) == 2
        assert result["Employee Data"][0]["code"] == "VIEW_EMPLOYEE_DATA"
        assert result["Employee Data"][0]["label"] == "View Employee Data"
        assert "Compensation" in result
        assert result["Compensation"][0]["code"] == "VIEW_COMPENSATION"

    def test_empty_xml(self):
        result = _parse_permission_metadata_xml("")
        assert result == {}

    def test_permission_without_label(self):
        """When label is missing, fall back to code as label."""
        xml = """<?xml version="1.0"?>
<permissionMetadata>
    <category name="Test">
        <permission>
            <code>TEST_CODE</code>
        </permission>
    </category>
</permissionMetadata>"""
        result = _parse_permission_metadata_xml(xml)
        assert result["Test"][0]["code"] == "TEST_CODE"
        assert result["Test"][0]["label"] == "TEST_CODE"


# ═══════════════════════════════════════════════════════════════════════════
# PermissionAnalyzer Tests (with mock client)
# ═══════════════════════════════════════════════════════════════════════════


class TestPermissionAnalyzer:
    """Tests for PermissionAnalyzer using mock SFClient."""

    def _make_analyzer(self, client=None):
        if client is None:
            client = MagicMock()
            client.base_url = "https://api4.sapsf.com/odata/v2"
        return PermissionAnalyzer(client)

    # ── get_permission_metadata ──

    def test_get_permission_metadata_success(self):
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client._request_with_retry.return_value = _mock_response(
            """<?xml version="1.0"?>
<permissionMetadata>
    <category name="Employee Data">
        <permission>
            <code>VIEW_EMP</code>
            <label>View Employee</label>
        </permission>
    </category>
</permissionMetadata>"""
        )
        analyzer = self._make_analyzer(client)
        result = analyzer.get_permission_metadata()
        assert "Employee Data" in result.categories
        assert result.categories["Employee Data"][0]["code"] == "VIEW_EMP"

    def test_get_permission_metadata_403(self):
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        resp = MagicMock()
        resp.text = "Access Denied"
        resp.status_code = 403
        client._request_with_retry.return_value = resp
        analyzer = self._make_analyzer(client)
        with pytest.raises(Exception, match="RBP administrator access"):
            analyzer.get_permission_metadata()

    # ── get_roles_permissions ──

    def test_get_roles_permissions_single_batch(self):
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client._request_with_retry.return_value = _mock_response(
            """<?xml version="1.0"?>
<rolePermissions>
    <role>
        <roleId>101</roleId>
        <roleName>HR Mgr</roleName>
        <permissions>
            <permission>VIEW_EMP</permission>
        </permissions>
    </role>
</rolePermissions>"""
        )
        analyzer = self._make_analyzer(client)
        result = analyzer.get_roles_permissions(["101"])
        assert "HR Mgr" in result

    def test_get_roles_permissions_multiple_batches(self):
        """Should batch when > 100 roles."""
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client._request_with_retry.return_value = _mock_response(
            """<?xml version="1.0"?>
<rolePermissions></rolePermissions>"""
        )
        analyzer = self._make_analyzer(client)
        # 150 roles should trigger 2 batches
        role_ids = [str(i) for i in range(150)]
        _ = analyzer.get_roles_permissions(role_ids)  # result unused - checking call_count
        assert client._request_with_retry.call_count >= 2

    def test_get_roles_permissions_empty_list(self):
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        analyzer = self._make_analyzer(client)
        result = analyzer.get_roles_permissions([])
        assert result == {}
        client._request_with_retry.assert_not_called()

    # ── get_user_roles_report ──

    def test_get_user_roles_report_success(self):
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client._request_with_retry.return_value = _mock_response(
            """<?xml version="1.0"?>
<userRolesReport>
    <userRole>
        <userName>john</userName>
        <roles><role>Admin</role></roles>
    </userRole>
</userRolesReport>"""
        )
        analyzer = self._make_analyzer(client)
        result = analyzer.get_user_roles_report(["john"])
        assert "john" in result
        assert result["john"] == ["Admin"]

    def test_get_user_roles_report_batching(self):
        """Should batch when > 100 users."""
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client._request_with_retry.return_value = _mock_response(
            """<?xml version="1.0"?>
<userRolesReport/>"""
        )
        analyzer = self._make_analyzer(client)
        user_ids = [f"user{i}" for i in range(250)]
        analyzer.get_user_roles_report(user_ids)
        assert client._request_with_retry.call_count >= 3

    # ── get_user_roles_by_user_id ──

    def test_get_user_roles_by_user_id_json(self):
        """getUserRolesByUserId returns JSON, not XML."""
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client._request_with_retry.return_value = _mock_response(
            json.dumps({"d": {"results": [{"roleName": "Admin", "roleId": "101"}]}})
        )
        analyzer = self._make_analyzer(client)
        result = analyzer.get_user_roles_by_user_id("john")
        assert len(result) == 1
        assert result[0]["roleName"] == "Admin"

    def test_get_user_roles_by_user_id_no_roles(self):
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client._request_with_retry.return_value = _mock_response(
            json.dumps({"d": {"results": []}})
        )
        analyzer = self._make_analyzer(client)
        result = analyzer.get_user_roles_by_user_id("nobody")
        assert result == []

    # ── get_users_permissions ──

    def test_get_users_permissions_success(self):
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client._request_with_retry.return_value = _mock_response(
            """<?xml version="1.0"?>
<usersPermissions>
    <userPermission>
        <userName>john</userName>
        <permissions>
            <permission>VIEW_EMP</permission>
        </permissions>
    </userPermission>
</usersPermissions>"""
        )
        analyzer = self._make_analyzer(client)
        result = analyzer.get_users_permissions(["john"])
        assert "john" in result
        assert "VIEW_EMP" in result["john"]

    # ── check_user_permission ──

    def test_check_user_permission_true(self):
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client._request_with_retry.return_value = _mock_response("true")
        analyzer = self._make_analyzer(client)
        assert analyzer.check_user_permission("john", "permType", "VIEW_EMP") is True

    def test_check_user_permission_false(self):
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client._request_with_retry.return_value = _mock_response("false")
        analyzer = self._make_analyzer(client)
        assert analyzer.check_user_permission("john", "permType", "VIEW_EMP") is False

    # ── get_users_by_dynamic_group ──

    def test_get_users_by_dynamic_group(self):
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client._request_with_retry.return_value = _mock_response(
            json.dumps({"d": {"results": [{"username": "john"}, {"username": "jane"}]}})
        )
        analyzer = self._make_analyzer(client)
        result = analyzer.get_users_by_dynamic_group("123")
        assert len(result) == 2

    def test_get_users_by_dynamic_group_xml_response(self):
        """Fallback gracefully when response isn't JSON."""
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client._request_with_retry.return_value = _mock_response("<xml></xml>")
        analyzer = self._make_analyzer(client)
        result = analyzer.get_users_by_dynamic_group("123")
        assert result == []

    # ── full_scan ──

    def test_full_scan_with_mock_data(self):
        """Test full scan orchestration with all mocking."""
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"

        # Mock User entity response
        client.get.return_value = [
            {"username": "john", "userId": "john", "firstName": "John", "lastName": "Doe", "status": "active"},
            {"username": "jane", "userId": "jane", "firstName": "Jane", "lastName": "Smith", "status": "active"},
        ]

        # Mock _request_with_retry for different RBP functions
        def mock_request(method, url, **kwargs):
            if "getUserRolesReport" in url:
                return _mock_response(
                    """<?xml version="1.0"?>
<userRolesReport>
    <userRole><userName>john</userName><roles><role>Admin</role><role>HR Mgr</role></roles></userRole>
    <userRole><userName>jane</userName><roles><role>HR Mgr</role></roles></userRole>
</userRolesReport>"""
                )
            elif "getRolesPermissions" in url:
                return _mock_response(
                    """<?xml version="1.0"?>
<rolePermissions>
    <role><roleId>101</roleId><roleName>Admin</roleName><permissions><permission>FULL_ACCESS</permission></permissions></role>
    <role><roleId>102</roleId><roleName>HR Mgr</roleName><permissions><permission>VIEW_EMP</permission><permission>MANAGE_COMP</permission></permissions></role>
</rolePermissions>"""
                )
            elif "getPermissionMetadata" in url:
                return _mock_response(
                    """<?xml version="1.0"?>
<permissionMetadata>
    <category name="General"><permission><code>FULL_ACCESS</code><label>Full Access</label></permission></category>
    <category name="Employee Data"><permission><code>VIEW_EMP</code><label>View Employee</label></permission></category>
    <category name="Compensation"><permission><code>MANAGE_COMP</code><label>Manage Comp</label></permission></category>
</permissionMetadata>"""
                )
            elif "getUsersPermissions" in url:
                return _mock_response(
                    """<?xml version="1.0"?>
<usersPermissions>
    <userPermission><userName>john</userName><permissions><permission>FULL_ACCESS</permission></permissions></userPermission>
    <userPermission><userName>jane</userName><permissions><permission>VIEW_EMP</permission><permission>MANAGE_COMP</permission></permissions></userPermission>
</usersPermissions>"""
                )
            return _mock_response("")

        client._request_with_retry.side_effect = mock_request

        analyzer = self._make_analyzer(client)
        report = analyzer.full_scan()

        assert report.total_roles == 2
        assert report.total_users == 2
        assert len(report.roles) == 2
        assert len(report.users) == 2
        assert report.catalogue is not None
        assert "General" in report.catalogue.categories

    def test_full_scan_no_users(self):
        """Handle tenant with no active users gracefully."""
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client.get.return_value = []
        client._request_with_retry.return_value = _mock_response("")

        analyzer = self._make_analyzer(client)
        report = analyzer.full_scan()

        assert report.total_users == 0
        assert report.total_roles == 0
        assert len(report.users) == 0

    def test_full_scan_user_fetch_fails(self):
        """When User entity fetch fails, should still return partial report."""
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        from sapsf_shared.exceptions import SFClientError
        client.get.side_effect = SFClientError(
            "Connection timeout", url="https://api4.sapsf.com/odata/v2/User"
        )
        # Mock RBP calls to handle Permission Metadata
        client._request_with_retry.return_value = _mock_response(
            """<?xml version="1.0"?><permissionMetadata/>"""
        )

        analyzer = self._make_analyzer(client)
        report = analyzer.full_scan()

        assert report.total_users == 0
        assert len(report.errors) >= 1

    def test_full_scan_with_inactive_users(self):
        """Inactive users should be flagged but included in the report."""
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"

        client.get.return_value = [
            {"username": "active1", "userId": "active1", "firstName": "Active", "lastName": "One", "status": "active"},
            {"username": "inactive1", "userId": "inactive1", "firstName": "Inactive", "lastName": "One", "status": "inactive"},
        ]

        def mock_request(method, url, **kwargs):
            if "getUserRolesReport" in url:
                return _mock_response(
                    """<?xml version="1.0"?>
<userRolesReport>
    <userRole><userName>active1</userName><roles><role>User</role></roles></userRole>
</userRolesReport>"""
                )
            elif "getRolesPermissions" in url:
                return _mock_response(
                    """<?xml version="1.0"?>
<rolePermissions>
    <role><roleId>101</roleId><roleName>User</roleName><permissions><permission>BASIC</permission></permissions></role>
</rolePermissions>"""
                )
            return _mock_response(
                """<?xml version="1.0"?>
<permissionMetadata/>"""
            )

        client._request_with_retry.side_effect = mock_request

        analyzer = self._make_analyzer(client)
        report = analyzer.full_scan()

        assert report.total_users == 2
        inactive_users = [u for u in report.users if u.is_inactive]
        assert len(inactive_users) == 1
        assert inactive_users[0].user_id == "inactive1"

    def test_full_scan_high_risk_detection(self):
        """Roles with sensitive permission combinations should be flagged."""
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client.get.return_value = [
            {"username": "admin", "userId": "admin", "firstName": "Admin", "lastName": "", "status": "active"},
        ]

        def mock_request(method, url, **kwargs):
            if "getUserRolesReport" in url:
                return _mock_response(
                    """<?xml version="1.0"?>
<userRolesReport>
    <userRole><userName>admin</userName><roles><role>Super Admin</role></roles></userRole>
</userRolesReport>"""
                )
            elif "getRolesPermissions" in url:
                return _mock_response(
                    """<?xml version="1.0"?>
<rolePermissions>
    <role><roleId>999</roleId><roleName>Super Admin</roleName><permissions>
        <permission>IMPORT_EXPORT_DATA</permission>
        <permission>MANAGE_COMPENSATION</permission>
        <permission>MANAGE_PERMISSION_ROLES</permission>
        <permission>MANAGE_SECURITY</permission>
        <permission>VIEW_PERSONAL_INFO</permission>
    </permissions></role>
</rolePermissions>"""
                )
            return _mock_response("""<?xml version="1.0"?><permissionMetadata/>""")

        client._request_with_retry.side_effect = mock_request

        analyzer = self._make_analyzer(client)
        report = analyzer.full_scan()

        assert len(report.high_risk_roles) >= 1
        risk_role_names = [r[0] for r in report.high_risk_roles]
        assert "Super Admin" in risk_role_names

    def test_full_scan_empty_roles_detected(self):
        """Roles with no permissions should be flagged."""
        client = MagicMock()
        client.base_url = "https://api4.sapsf.com/odata/v2"
        client.get.return_value = [
            {"username": "user1", "userId": "user1", "firstName": "User", "lastName": "1", "status": "active"},
        ]

        def mock_request(method, url, **kwargs):
            if "getUserRolesReport" in url:
                return _mock_response(
                    """<?xml version="1.0"?>
<userRolesReport>
    <userRole><userName>user1</userName><roles><role>Orphan Role</role></roles></userRole>
</userRolesReport>"""
                )
            elif "getRolesPermissions" in url:
                return _mock_response(
                    """<?xml version="1.0"?>
<rolePermissions>
    <role><roleId>000</roleId><roleName>Orphan Role</roleName><permissions/></role>
</rolePermissions>"""
                )
            return _mock_response("""<?xml version="1.0"?><permissionMetadata/>""")

        client._request_with_retry.side_effect = mock_request

        analyzer = self._make_analyzer(client)
        report = analyzer.full_scan()

        assert len(report.empty_roles) >= 1
        assert report.empty_roles[0].role_name == "Orphan Role"


# ═══════════════════════════════════════════════════════════════════════════
# Risk Flagging Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestRiskFlagging:
    """Tests for the risk flagging logic."""

    def test_dangerous_combo_detected(self):
        analyzer = PermissionAnalyzer(MagicMock())
        roles = [
            PermissionRole(
                role_id="101",
                role_name="High Risk Role",
                permissions=["IMPORT_EXPORT_DATA", "MANAGE_COMPENSATION", "VIEW_PERSONAL_INFO"],
            )
        ]
        flags = analyzer._flag_high_risk_roles(roles, None)
        assert len(flags) >= 1

    def test_safe_role_not_flagged(self):
        analyzer = PermissionAnalyzer(MagicMock())
        roles = [
            PermissionRole(
                role_id="102",
                role_name="Safe Role",
                permissions=["VIEW_BASIC_INFO", "SELF_SERVICE"],
            )
        ]
        flags = analyzer._flag_high_risk_roles(roles, None)
        assert len(flags) == 0

    def test_empty_role_not_flagged_as_high_risk(self):
        analyzer = PermissionAnalyzer(MagicMock())
        roles = [
            PermissionRole(
                role_id="103",
                role_name="Empty Role",
                permissions=[],
                is_empty=True,
            )
        ]
        flags = analyzer._flag_high_risk_roles(roles, None)
        assert len(flags) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Excel Export Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestExcelExport:
    """Smoke tests for Excel export (requires openpyxl)."""

    def test_export_to_excel(self):
        """Export a report to Excel and verify file exists."""
        pytest.importorskip("openpyxl")

        report = PermissionScanReport(
            roles=[
                PermissionRole(role_id="101", role_name="Admin", permissions=["FULL_ACCESS"], user_count=2),
                PermissionRole(role_id="102", role_name="Empty", permissions=[], is_empty=True),
            ],
            users=[
                UserRoleAssignment(user_id="u1", username="user1", full_name="User One", status="active",
                                   role_ids=["Admin"], role_names=["Admin"]),
                UserRoleAssignment(user_id="u2", username="user2", full_name="User Two", status="active",
                                   role_ids=["Empty"], role_names=["Empty"]),
            ],
            catalogue=PermissionCatalogue(categories={
                "General": [{"code": "FULL_ACCESS", "label": "Full Access"}],
            }),
            tenant_url="https://api4.sapsf.com",
            total_roles=2,
            total_users=2,
            empty_roles=[],
            high_risk_roles=[],
            errors=[],
        )

        analyzer = PermissionAnalyzer(MagicMock())

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            tmp_path = f.name

        try:
            analyzer.export_to_excel(report, tmp_path)
            assert os.path.exists(tmp_path)
            assert os.path.getsize(tmp_path) > 0

            # Read back to verify sheets
            import openpyxl
            wb = openpyxl.load_workbook(tmp_path)
            sheet_names = wb.sheetnames
            assert "Summary" in sheet_names
            assert "Roles" in sheet_names
            assert "Users" in sheet_names
            assert "Empty Roles" in sheet_names
            assert "Permission Catalogue" in sheet_names
            assert "Risk Flags" in sheet_names
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_export_to_excel_no_catalogue(self):
        """Export works even without permission catalogue."""
        pytest.importorskip("openpyxl")

        report = PermissionScanReport(
            roles=[],
            users=[],
            catalogue=None,
            tenant_url="https://api4.sapsf.com",
        )

        analyzer = PermissionAnalyzer(MagicMock())

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            tmp_path = f.name

        try:
            analyzer.export_to_excel(report, tmp_path)
            assert os.path.exists(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


# ═══════════════════════════════════════════════════════════════════════════
# PermissionScanReport & Dataclass Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestPermissionScanReport:
    """Tests for the report dataclass."""

    def test_empty_report_defaults(self):
        report = PermissionScanReport(roles=[], users=[], catalogue=None, tenant_url="test")
        assert report.total_roles == 0
        assert report.total_users == 0
        assert report.empty_roles == []
        assert report.high_risk_roles == []
        assert report.errors == []

    def test_report_with_data(self):
        role = PermissionRole(role_id="1", role_name="Test Role", permissions=["P1"])
        user = UserRoleAssignment(user_id="u1", username="test", full_name="Test User", status="active", role_ids=["1"])
        report = PermissionScanReport(
            roles=[role],
            users=[user],
            catalogue=None,
            tenant_url="test",
            total_roles=1,
            total_users=1,
        )
        assert report.total_roles == 1
        assert report.roles[0].role_name == "Test Role"
        assert report.users[0].username == "test"


# ═══════════════════════════════════════════════════════════════════════════
# Regex Parser Edge Cases
# ═══════════════════════════════════════════════════════════════════════════


class TestRegexParsers:
    """Tests for regex-based XML fallback parsers."""

    def test_regex_role_permissions_multiline(self):
        xml = """<rolePermissions>
<role>
<roleName>Role 1</roleName>
<permissions>
<permission>A</permission>
<permission>B</permission>
</permissions>
</role>
</rolePermissions>"""
        result = _parse_role_permissions_regex(xml)
        assert "Role 1" in result
        assert result["Role 1"] == ["A", "B"]

    def test_regex_user_roles(self):
        xml = """<userRolesReport>
<userRole>
<userName>user1</userName>
<roles>
<role>Role X</role>
</roles>
</userRole>
</userRolesReport>"""
        result = _parse_user_roles_regex(xml)
        assert "user1" in result
        assert result["user1"] == ["Role X"]

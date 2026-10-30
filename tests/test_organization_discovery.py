"""Organization discovery is paginated inventory, never account access proof."""

import pytest

from security_lakehouse.organization_discovery import discover_accounts


class Client:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.requests = []

    def list_accounts(self, **kwargs):
        self.requests.append(kwargs)
        page = next(self.pages)
        if isinstance(page, Exception):
            raise page
        return page


def account(number):
    return {"Id": f"{number:012}", "Name": f"Account {number}", "State": "ACTIVE", "Email": "private@example.test"}


def test_discovery_follows_empty_pages_and_does_not_claim_access():
    client = Client(
        [
            {"Accounts": [account(1)], "NextToken": "next"},
            {"Accounts": [], "NextToken": "last"},
            {"Accounts": [account(2), account(3)]},
        ]
    )
    result = discover_accounts(client)
    assert result["complete"] is True
    assert len(result["accounts"]) == 3
    assert client.requests[-1]["NextToken"] == "last"
    assert "Email" not in str(result)
    assert all(row["access"] == "not_tested" for row in result["accounts"])


@pytest.mark.parametrize(
    "pages,limit",
    [
        ([{"Accounts": [account(1)], "NextToken": "loop"}, {"Accounts": [], "NextToken": "loop"}], 5),
        ([{"Accounts": [account(1)], "NextToken": "more"}], 1),
        (
            [
                {"Accounts": [account(1)]},
            ],
            0,
        ),
        ([PermissionError("credential secret")], 5),
        ([{"Accounts": [{"Name": "missing id"}]}], 5),
    ],
)
def test_incomplete_discovery_never_looks_complete(pages, limit):
    result = discover_accounts(Client(pages), max_pages=limit)
    assert result["complete"] is False
    assert result["error"]
    assert "credential secret" not in str(result)


def test_discovery_uses_named_delegation_without_enabling_members(tmp_path, monkeypatch):
    from security_lakehouse import connectors_aws
    from security_lakehouse.connections import list_connections
    from security_lakehouse.connector_state import append_config_event
    from security_lakehouse.organization_discovery import discover_organization
    from security_lakehouse.organization_scopes import organization_scope, save_organization
    from test_named_connections import prepare

    child = prepare(tmp_path, "management", "000000000001")
    append_config_event(
        child,
        connector_id="aws-posture",
        state="enabled",
        actor="test",
        credentials={
            "account_id": "000000000001",
            "role_arn": "arn:aws:iam::000000000001:role/ReadOnly",
            "external_id": "reference",
        },
    )
    save_organization(tmp_path, organization_id="org", name="Org", connection_ids=["management"])
    supplied = []

    class AWS:
        def __init__(self, **kwargs):
            supplied.append(kwargs)

        def caller_identity(self):
            return {"Account": "000000000001"}

        def service_client(self, service):
            assert service == "organizations"
            return Client([{"Accounts": [account(1), account(2), account(3)]}])

    monkeypatch.setattr(connectors_aws, "AWSClient", AWS)
    result = discover_organization(tmp_path, "org", "management")
    assert result["complete"]
    assert supplied[0]["role_arn"].endswith("role/ReadOnly")
    assert len(list_connections(tmp_path)) == 1
    assert organization_scope(tmp_path, "org")["connection_ids"] == ["management"]

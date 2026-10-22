"""Shared POST handlers do not turn exception details into response bodies."""

from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from security_lakehouse import api_v1
from security_lakehouse.mapping_review import MappingReviewError
from security_lakehouse.server_app import create_app
from security_lakehouse.services.assessments import GenerationConflict

MARKER = "private-token /srv/private/customer.json SELECT secret FROM credentials"


@pytest.mark.parametrize(
    ("route", "target", "exception", "body", "status"),
    [
        (
            "repositories/public-audit",
            "security_lakehouse.services.public_repositories.validate_request",
            ValueError,
            {},
            400,
        ),
        ("snapshots", "security_lakehouse.services.assessments.snapshot", GenerationConflict, {}, 409),
        ("ingestion/eval", "security_lakehouse.services.assessments.evaluate", GenerationConflict, {}, 409),
        ("connectors/aws-posture/link/start", "security_lakehouse.cloud_linking.start_cloud_link", ValueError, {}, 400),
        (
            "connectors/aws-posture/link/complete",
            "security_lakehouse.cloud_linking.complete_cloud_link",
            ValueError,
            {"session_id": "test-session"},
            400,
        ),
    ],
)
def test_post_errors_never_echo_exception_details(tmp_path, monkeypatch, route, target, exception, body, status):
    def fail(*args, **kwargs):
        raise exception(MARKER)

    monkeypatch.setattr(target, fail)
    code, payload = api_v1.handle_post(f"/api/v1/{route}", body, tmp_path)
    assert code == status
    assert MARKER not in repr(payload)
    assert payload["errors"][0]["detail"]

    # Verify the actual HTTP projection, not only the handler result.
    client = TestClient(create_app(tmp_path, require_auth=False))
    response = client.post(f"/api/v1/{route}", json=body)
    assert response.status_code == status
    assert MARKER not in response.text


def test_mapping_review_error_never_echoes_exception_details(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise MappingReviewError(MARKER)

    monkeypatch.setattr(api_v1, "record_decisions", fail)
    code, payload = api_v1.record_mapping_review(
        {"items": []}, tmp_path, reviewer="reviewer", auth_method="local-unauthenticated"
    )
    assert code == HTTPStatus.BAD_REQUEST
    assert MARKER not in repr(payload)
    assert payload["errors"][0]["detail"]

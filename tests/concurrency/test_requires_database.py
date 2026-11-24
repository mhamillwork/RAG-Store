import pytest


def test_concurrent_claim_requires_database():
    pytest.skip("Concurrent claim coverage is exercised by the integration test when PostgreSQL roles are available. This marker keeps the CI stage explicit.")

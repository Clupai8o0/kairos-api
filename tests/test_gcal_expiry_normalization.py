from datetime import datetime, timedelta, timezone

from kairos.models.google_account import GoogleAccount
from kairos.models.user import User
from kairos.services.gcal_service import GCalService


def test_get_credentials_normalizes_aware_expiry_to_naive_utc() -> None:
    service = GCalService()
    user = User(
        email="sam@test.com",
        google_id="google_1",
        google_access_token="token",
        google_refresh_token="refresh",
        google_token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
        preferences={},
    )

    creds = service._get_credentials(user)
    assert creds.expiry is not None
    assert creds.expiry.tzinfo is None


def test_get_credentials_normalizes_account_aware_expiry_to_naive_utc() -> None:
    service = GCalService()
    user = User(
        email="sam@test.com",
        google_id="google_1",
        google_access_token="token",
        google_refresh_token="refresh",
        preferences={},
    )
    account = GoogleAccount(
        user_id="u1",
        google_account_id="acct_1",
        email="sam+1@test.com",
        access_token="token",
        refresh_token="refresh",
        token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
        scopes=["https://www.googleapis.com/auth/calendar"],
    )

    creds = service._get_credentials(user, account)
    assert creds.expiry is not None
    assert creds.expiry.tzinfo is None

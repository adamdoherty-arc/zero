"""Google People API photo lookup (Feature-57).

Resolves an attendee email to a Google profile photo so the meeting
pipeline can auto-enroll a faceprint without manual upload.

Uses the existing Gmail OAuth credentials (multi-account safe). Requires
the ``contacts.readonly`` and ``directory.readonly`` scopes — added to
GOOGLE_SCOPES in gmail_oauth_service.py. Existing accounts must re-auth
once to pick up the new scope; until then ``fetch_photo`` returns None
and the pipeline silently skips this attendee.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)


class GooglePeopleService:
    """Light wrapper over googleapiclient.discovery for the People API."""

    async def fetch_photo(self, email: str, *, account_id: Optional[str] = None) -> Optional[bytes]:
        """Return the JPEG bytes of the contact's profile photo, or None.

        Resolves via the People API ``people.searchDirectoryPeople`` endpoint
        (works for Google Workspace directory members). For consumer Gmail
        contacts it falls back to ``people.connections.list`` which returns
        the user's own saved contacts.
        """
        if not email or "@" not in email:
            return None

        from app.services.gmail_oauth_service import get_gmail_oauth_service

        oauth = get_gmail_oauth_service()
        creds = await oauth.get_credentials(account_id=account_id)
        if creds is None:
            return None
        try:
            from googleapiclient.discovery import build
        except Exception as exc:  # noqa: BLE001
            logger.debug("google_people_googleapiclient_missing", error=str(exc))
            return None

        try:
            service = build("people", "v1", credentials=creds, cache_discovery=False)
        except Exception as exc:  # noqa: BLE001
            logger.debug("google_people_build_failed", error=str(exc))
            return None

        photo_url = self._search_directory(service, email) or self._search_contacts(service, email)
        if not photo_url:
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(photo_url)
                if resp.status_code != 200:
                    logger.debug("google_people_photo_fetch_failed", email=email, status=resp.status_code)
                    return None
                # Strip Google's "=s100" sizing suffix to get a larger photo
                # via the URL — but the response is what it is, so accept it.
                return resp.content
        except Exception as exc:  # noqa: BLE001
            logger.debug("google_people_photo_http_failed", email=email, error=str(exc))
            return None

    def _search_directory(self, service, email: str) -> Optional[str]:
        """Search the Workspace directory for the email. Returns photo URL."""
        try:
            resp = (
                service.people()
                .searchDirectoryPeople(
                    query=email,
                    readMask="photos,emailAddresses",
                    sources=[
                        "DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE",
                        "DIRECTORY_SOURCE_TYPE_DOMAIN_CONTACT",
                    ],
                )
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("google_people_directory_search_failed", email=email, error=str(exc))
            return None
        return self._extract_photo(resp.get("people", []), email)

    def _search_contacts(self, service, email: str) -> Optional[str]:
        """Search the user's contacts. Returns photo URL."""
        try:
            resp = (
                service.people()
                .searchContacts(
                    query=email,
                    readMask="photos,emailAddresses",
                )
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("google_people_contacts_search_failed", email=email, error=str(exc))
            return None
        results = resp.get("results", []) or []
        people = [r.get("person", {}) for r in results]
        return self._extract_photo(people, email)

    def _extract_photo(self, people: list[dict], email: str) -> Optional[str]:
        for p in people:
            emails = p.get("emailAddresses", []) or []
            if not any((e.get("value") or "").lower() == email.lower() for e in emails):
                continue
            for photo in p.get("photos", []) or []:
                url = photo.get("url")
                if url and not photo.get("default", False):
                    return url
        return None


@lru_cache()
def get_google_people_service() -> GooglePeopleService:
    return GooglePeopleService()

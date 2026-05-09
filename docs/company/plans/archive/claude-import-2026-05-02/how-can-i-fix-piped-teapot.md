# Fix: Google OAuth 403 "access_denied" for hdoherty@eightfold.ai

## Context

Signing in to Zero with `hdoherty@eightfold.ai` hits a Google consent screen that reads *"Access blocked: Zero has not completed the Google verification process"* with `Error 403: access_denied`.

Zero's OAuth client is configured in Google Cloud Console as an **unverified app in "Testing" publishing status**. In that state Google only allows up to 100 accounts that are explicitly listed as test users on the OAuth consent screen. `hdoherty@eightfold.ai` is not on that list, so Google rejects the consent before it ever reaches our backend.

This is a **Google Cloud Console configuration fix**, not a code change. The backend's OAuth flow is correct — it just hands off to Google, which is doing the blocking. Confirmed by reading:

- [backend/app/routers/google_oauth.py:43-63](backend/app/routers/google_oauth.py#L43-L63) — initiates auth
- [backend/app/services/gmail_oauth_service.py:37-43](backend/app/services/gmail_oauth_service.py#L37-L43) — scopes
- [backend/app/services/gmail_oauth_service.py:158-272](backend/app/services/gmail_oauth_service.py#L158-L272) — auth URL + token exchange
- [backend/app/infrastructure/config.py:89-91](backend/app/infrastructure/config.py#L89-L91) — `ZERO_GOOGLE_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI`

Scopes requested (all sensitive/restricted, which is why verification would otherwise be required):
`gmail.readonly`, `gmail.labels`, `gmail.modify`, `calendar`, `calendar.events`.

## Recommended Fix: Add the email as a test user

1. Open https://console.cloud.google.com/apis/credentials/consent
2. Make sure the project selector (top bar) is on the **same Google Cloud project that owns the OAuth client** whose Client ID is in `ZERO_GOOGLE_CLIENT_ID` in your `.env`. To confirm:
   - `grep ZERO_GOOGLE_CLIENT_ID .env` → note the `...apps.googleusercontent.com` value
   - In Cloud Console → **APIs & Services → Credentials**, the OAuth 2.0 Client IDs list should show that same ID. The project shown at the top of that page is the one you need.
3. In the left nav click **OAuth consent screen** (or **Audience** in the newer UI).
4. Confirm **Publishing status: Testing** and **User type: External**.
5. Scroll to **Test users** → click **+ ADD USERS** → enter `hdoherty@eightfold.ai` → **SAVE**.
6. Back in the browser, close the blocked Google tab and retry the sign-in from Zero: visit `http://localhost:18792/api/google/auth/url` (or whatever entry point the UI uses) and sign in again as `hdoherty@eightfold.ai`. The consent screen should now appear with the unverified-app warning ("Continue" after clicking Advanced) instead of the hard 403.

No `.env`, no Docker rebuild, no backend restart needed — Google picks up the test-users change within seconds.

## Alternatives (only if #1 is insufficient)

- **Use a test-approved account instead.** If another email is already a listed test user, sign in with that one. Zero supports multiple accounts in the `oauth_accounts` table, so this is purely about whose inbox you're connecting.
- **Publish the app.** Switching publishing status from Testing → In production lifts the 100-user cap, BUT because we request `gmail.*` and `calendar` (sensitive/restricted) scopes, Google will require full OAuth verification including a brand review, scope justification, and (for restricted scopes) a CASA security assessment. This takes weeks and costs money — not the right move for a self-hosted dev tool. Skip unless you genuinely need non-test users.
- **Different Google Cloud project with per-user Internal type.** Not applicable — `eightfold.ai` is not the Workspace domain that owns this Google Cloud project, so "Internal" user type would not cover that email anyway.

## Verification

After adding the test user:

1. Retry OAuth from the UI → expect to land on the "Google hasn't verified this app" screen, click **Advanced → Go to Zero (unsafe)** → grant scopes.
2. On success, Google redirects to `http://localhost:18792/api/google/auth/callback`, which stores the token and redirects to the frontend with `?gmail_connected=true`.
3. Verify the account was stored:
   ```bash
   docker exec -it zero-pg psql -U postgres -d zero -c "SELECT email, is_active, scopes FROM oauth_accounts WHERE email='hdoherty@eightfold.ai';"
   ```
4. Trigger a sync and check backend logs for errors:
   ```bash
   docker logs --tail 50 zero-api 2>&1 | grep -iE "oauth|gmail|403"
   ```

## Files touched

**None.** This is a Google Cloud Console configuration change only.

# Fix Robinhood SMS vs Push Notification Issue

## Context

You're experiencing a known Robinhood authentication issue where the system is sending SMS codes instead of push notifications for device verification. This happens because your device token (stored in the pickle file) is associated with a previous SMS workflow, causing Robinhood's server to prefer SMS for subsequent logins.

**Root Cause**: Device token `f6a87b9d-7524-4f...` in `/app/.tokens/robinhood.pickle` is linked to SMS verification workflow from previous authentication attempts.

**Impact**: You can't complete verification because you have no way to receive SMS codes, but the system keeps requesting SMS instead of sending push notifications to your Robinhood mobile app.

## Solution Approach

### Phase 1: Reset Device Token (Immediate Fix)
Delete the existing pickle file to force generation of a fresh device token, which will reset Robinhood's association and restore push notifications.

### Phase 2: Re-authenticate with Push Notifications
Force a new connection attempt that should now receive push notifications instead of SMS.

### Phase 3: Setup TOTP (Long-term Prevention)
Configure TOTP (Time-based One-Time Password) authentication to completely bypass device verification in the future.

## Implementation Plan

### Step 1: Check Current Authentication Status
- Verify current Robinhood connection status via diagnostics endpoint
- Document the current device token and challenge type being used

### Step 2: Delete Device Token Pickle File
- Remove the existing pickle file: `rm -f /app/.tokens/robinhood.pickle`
- This forces generation of a completely fresh device token
- **Critical**: This is different from "clear session" which preserves the device token

### Step 3: Force Fresh Authentication
- Trigger new authentication via `POST /api/settings/robinhood/force-connect`
- Monitor logs to confirm challenge type is now `prompt` (push) instead of `sms`
- Wait for push notification in your Robinhood mobile app

### Step 4: Setup TOTP for Future (Recommended)
- Guide you through setting up TOTP in your Robinhood app
- Add `ROBINHOOD_TOTP=<secret>` to `.env` file
- This eliminates device approval requirements permanently

### Step 5: Verify Fix
- Test portfolio sync functionality
- Confirm authentication works without SMS codes
- Monitor system for successful Robinhood data fetching

## Key Files to Modify
- `/app/.tokens/robinhood.pickle` (delete)
- `.env` (add TOTP secret)

## Critical Endpoints
- `GET /api/settings/robinhood/diagnostics` - Check status
- `POST /api/settings/robinhood/force-connect` - Trigger re-auth
- `GET /api/settings/robinhood` - Monitor connection state

## Success Criteria
1. ✅ Device token reset completed (pickle file deleted)
2. ✅ New authentication attempt shows `Challenge type: prompt` in logs
3. ✅ Push notification received and approved in Robinhood mobile app
4. ✅ Portfolio sync completes successfully
5. ✅ TOTP configured for future authentication (optional but recommended)

## Backup Plan
If push notifications still don't work after device token reset:
- Wait 15-30 minutes for SMS workflow to expire naturally
- Check if TOTP can be configured immediately to bypass device verification
- Investigate rate limiting or throttling issues with Robinhood's push endpoint

## Reference Documentation
- `.claude/memory/topics/robinhood.md` - General Robinhood integration
- `.claude/memory/topics/robinhood-device-verification.md` - Device verification specifics
- `backend/infrastructure/robinhood_auth.py` - Authentication implementation
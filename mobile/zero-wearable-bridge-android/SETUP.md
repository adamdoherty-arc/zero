# Getting Meta Ray-Ban Meta → Zero working end-to-end

You signed up at [wearables.developer.meta.com](https://wearables.developer.meta.com/).
Here's the exact ordered sequence to go from "account created" to
"glasses streaming into Zero."

## 1. Register an app in the Wearables Developer Center

Log into [wearables.developer.meta.com](https://wearables.developer.meta.com/) →
**Apps** → **Create App**. Pick a display name (e.g. "Zero Wearable Bridge").

You'll get back two values:

- `APPLICATION_ID` — numeric-looking identity.
- `CLIENT_TOKEN` — attestation token.

Keep these two; we'll paste them in step 4.

> For *initial* testing you can skip app registration entirely and use
> **Developer Mode** (set `APPLICATION_ID=0`, leave `CLIENT_TOKEN` empty).
> The app can then sideload and pair with glasses that have developer
> mode enabled, but can't be published. Fastest path to a running demo.

## 2. Create a GitHub personal access token

The DAT SDK is shipped via GitHub Packages, which is gated on a token.

- Go to [github.com/settings/tokens](https://github.com/settings/tokens) →
  **Generate new token (classic)**.
- Scope: just `read:packages`.
- Copy the `ghp_…` string.

## 3. Pair your glasses to your phone

- Install **Meta AI** (or Meta View, if you're on an older Ray-Ban build)
  from the Play Store.
- Put Ray-Ban Meta in pairing mode. Approve the pair in Meta AI.
- In Meta AI settings, enable **Developer Mode** on the glasses so
  sideloaded apps (including this bridge) can bind.

## 4. Fill in `local.properties`

In this project root (`mobile/zero-wearable-bridge-android/`):

```bash
cp local.properties.example local.properties
```

Edit `local.properties`:

```properties
github_token=ghp_<paste from step 2>
meta.application.id=<from step 1, or "0" for Developer Mode>
meta.client.token=<from step 1, or empty for Developer Mode>
```

## 5. Fill in `app/src/main/assets/zero.properties`

```bash
cp app/src/main/assets/zero.properties.example \
   app/src/main/assets/zero.properties
```

Edit:

```properties
zero.api.url=http://<your-laptop-lan-ip>:18792
zero.api.token=<ZERO_GATEWAY_TOKEN from c:\code\zero\.env>
zero.sight.provider=meta_rayban
zero.fallback.phone=true   # auto-fallback to phone camera if glasses unpaired
```

## 6. Build + install

```bash
./gradlew :app:installDebug
```

(Or open the folder in Android Studio and click Run ▶ on your paired phone.)

## 7. First run

On the phone, open "Zero Wearable Bridge":

1. Tap **Pair with Ray-Ban Meta (one-time)**. This calls
   `Wearables.startRegistration()`, which hands off to the Meta AI app,
   shows the user a pairing prompt, and returns here via the
   `zero-wearable-bridge://` intent filter (already in the manifest).
2. Grant camera + mic + notification permissions.
3. Tap **Start service**.
4. The persistent notification switches to:
   - "Zero is watching (glasses)" if DAT bound, or
   - "Zero is watching (phone camera — no glasses paired)" if not.

## 8. Tell Zero to use the glasses feed

On your laptop:

```bash
curl -H "Content-Type: application/json" \
     -d '{"provider":"meta_rayban"}' \
     http://localhost:18792/api/sight/select
```

## 9. Verify frames are flowing

```bash
curl http://localhost:18792/api/sight/providers
# Expect: "meta_rayban": {"active": true, "last_frame_ts": <recent>, ...}

curl -X POST "http://localhost:18792/api/reachy/vision/scene?provider_id=meta_rayban"
# Expect: {"caption": "<description of whatever you're looking at>", "model": "gemini-flash-latest", ...}
```

You should also see vault files appearing under
`c:\code\vault\ObsidianZero\00_Meta\_agent\vision\{date}\` — one per
minute-ish when the scene changes.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Gradle: `Could not resolve com.meta.wearable:mwdat-core` | `github_token` missing or wrong scope | Verify token has `read:packages` scope. Either set `GITHUB_TOKEN` env var or `github_token=...` in `local.properties`. |
| `Pair` button does nothing | Meta AI app not installed, or glasses not in dev mode | Install Meta AI, put glasses in dev mode via Meta AI → Settings. |
| Service says "phone camera — no glasses paired" even after pairing | `APPLICATION_ID=0` + glasses dev mode not enabled, OR pairing didn't complete the callback | Re-check the intent filter fired (logcat for `GlassesSession`). |
| Frames arrive in host_agent but not in Zero UI | Eyes-off toggled ON in the top nav | Click the **Eyes off** button in TopBar to turn it green. |
| Gemini returns empty captions | `ZERO_VLM_MODEL` env points at something unmapped in LiteLLM | Default is `gemini-flash-latest` — verified working. Override only if you have a reason. |

## What happens after it's running

- Every minute, `ambient_vision_tick` in `zero-api` pulls the latest
  glasses frame, runs VLM (Gemini 3.x via shared LiteLLM), writes to
  the vault, and surfaces actionable items (sticky notes, receipts,
  whiteboards) to the agent approval queue.
- Every voice turn to Reachy auto-prepends *"You can see: X"* to the
  persona prompt. Ask *"Reachy, what did I just walk past?"* and it
  answers grounded in the frame, not a hallucination.
- "What do you see" / "Read this note" intercepts bypass the LLM and
  hit the VLM directly, with a `[observe]` gesture so Reachy leans in.
- Morning briefing contains a "What you saw" section.

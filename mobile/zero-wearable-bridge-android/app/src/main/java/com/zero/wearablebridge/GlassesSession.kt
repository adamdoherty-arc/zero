package com.zero.wearablebridge

import android.content.Context
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel

/**
 * Glasses session stub — the real DAT SDK wiring plugs in here.
 *
 * The Meta Wearables DAT SDK 0.6.0 exposes these concrete types (verified
 * by inspecting the installed AAR):
 *
 *   com.meta.wearable.dat.core.Wearables
 *   com.meta.wearable.dat.core.selectors.AutoDeviceSelector
 *   com.meta.wearable.dat.core.session.Session
 *   com.meta.wearable.dat.core.types.Permission
 *   com.meta.wearable.dat.camera.StreamSession
 *   com.meta.wearable.dat.camera.SessionStreamExtensionsKt
 *   com.meta.wearable.dat.camera.types.StreamConfiguration
 *   com.meta.wearable.dat.camera.types.VideoFrame
 *   com.meta.wearable.dat.camera.types.AudioFrame
 *   com.meta.wearable.dat.camera.types.PhotoData
 *   com.meta.wearable.dat.camera.types.VideoQuality
 *
 * Follow the sample app in the DAT Android repo to wire these up:
 * https://github.com/facebook/meta-wearables-dat-android/tree/main/app
 *
 * Until this is wired, [isConnected] stays `false` and [MainService]
 * automatically falls back to the phone camera so the pipe to Zero is
 * live end-to-end regardless.
 */
class GlassesSession(
    private val context: Context,
    private val uplink: ZeroUplink,
    private val privacy: PrivacyState,
) {

    @Suppress("unused")
    private val scope = CoroutineScope(Dispatchers.IO + Job())

    /** Set by [start] once a DAT session is actually bound. */
    @Volatile var isConnected: Boolean = false
        private set

    suspend fun start() {
        // TODO(DAT): copy the sample app's registration + session bootstrap.
        // Typical shape (compiled against real types; adjust as needed):
        //
        //   com.meta.wearable.dat.core.Wearables.initialize(context.applicationContext)
        //   val session = Wearables.createSession(AutoDeviceSelector()).getOrNull() ?: return
        //   val stream = StreamSession.from(session, StreamConfiguration(...))
        //   stream.videoFrames.collect { frame -> onVideo(frame) }
        //   stream.audioFrames.collect { frame -> onAudio(frame) }
        //   isConnected = true
        Log.i(TAG, "GlassesSession.start — DAT wiring pending; see class doc")
    }

    fun stop() {
        isConnected = false
        scope.cancel()
    }

    companion object {
        private const val TAG = "GlassesSession"
    }
}

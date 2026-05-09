package com.zero.wearablebridge

import android.content.Context
import android.util.Base64
import android.util.Log
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.Properties
import java.util.concurrent.TimeUnit

/**
 * HTTPS / WebSocket client for Zero's `/api/sight/{provider}/...` endpoints.
 *
 * - `POST /ingest` — JPEG frames (multipart).
 * - `POST /audio-chunk` — base64 PCM16 + sample rate (JSON).
 * - `WS /notify` — server → client TTS / text hints; subclass reads them
 *    and hands off to [NotificationSink] for playback through the glasses.
 */
class ZeroUplink(
    private val context: Context,
    private val privacy: PrivacyState,
) {

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    private lateinit var baseUrl: String
    private lateinit var token: String
    private lateinit var provider: String

    private val scope = CoroutineScope(Dispatchers.IO + Job())
    private var notifySocket: WebSocket? = null

    private val notifySink = NotificationSink(context)

    fun start() {
        val props = loadProps()
        baseUrl = (props.getProperty("zero.api.url") ?: error("zero.api.url missing")).trimEnd('/')
        token = props.getProperty("zero.api.token") ?: ""
        provider = props.getProperty("zero.sight.provider") ?: "meta_rayban"

        // Open the notify WebSocket so Zero can push TTS back to the glasses.
        val wsUrl = baseUrl.replaceFirst("http", "ws") + "/api/sight/$provider/notify"
        val req = Request.Builder().url(wsUrl).header("Authorization", "Bearer $token").build()
        notifySocket = client.newWebSocket(req, NotifyListener())
    }

    fun stop() {
        notifySocket?.close(1000, "service_stop")
        scope.coroutineContext[Job]?.cancel()
    }

    // ---- Outbound ----------------------------------------------------------

    suspend fun postFrame(jpeg: ByteArray) {
        if (jpeg.isEmpty()) return
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                "frame.jpg",
                jpeg.toRequestBody("image/jpeg".toMediaType()),
            )
            .build()
        val req = Request.Builder()
            .url("$baseUrl/api/sight/$provider/ingest")
            .header("Authorization", "Bearer $token")
            .post(body)
            .build()
        runCatching {
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) {
                    Log.w(TAG, "postFrame non-2xx: ${resp.code}")
                }
            }
        }.onFailure { Log.w(TAG, "postFrame failed", it) }
    }

    suspend fun postAudio(pcm16: ByteArray, sampleRate: Int) {
        if (pcm16.isEmpty()) return
        val body = JSONObject().apply {
            put("pcm16_b64", Base64.encodeToString(pcm16, Base64.NO_WRAP))
            put("sample_rate", sampleRate)
        }
        val req = Request.Builder()
            .url("$baseUrl/api/sight/$provider/audio-chunk")
            .header("Authorization", "Bearer $token")
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .build()
        runCatching { client.newCall(req).execute().close() }
            .onFailure { Log.w(TAG, "postAudio failed", it) }
    }

    suspend fun notifyEvent(kind: String, payload: String?) {
        // Simple event forwarder; maps to Zero's agent approval queue later.
        val body = JSONObject().apply {
            put("kind", kind)
            if (payload != null) put("payload", payload)
        }
        val req = Request.Builder()
            .url("$baseUrl/api/sight/$provider/notify")
            .header("Authorization", "Bearer $token")
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .build()
        runCatching { client.newCall(req).execute().close() }
    }

    // ---- Inbound ------------------------------------------------------------

    private inner class NotifyListener : WebSocketListener() {
        override fun onMessage(webSocket: WebSocket, text: String) {
            Log.i(TAG, "notify msg: ${text.take(120)}")
            val payload = runCatching { JSONObject(text) }.getOrNull() ?: return
            val msg = payload.optString("text", "")
            if (msg.isNotBlank()) {
                scope.launch { notifySink.speak(msg) }
            }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: okhttp3.Response?) {
            Log.w(TAG, "notify socket failed", t)
        }
    }

    // ---- Config -------------------------------------------------------------

    private fun loadProps(): Properties {
        val props = Properties()
        runCatching {
            context.assets.open("zero.properties").use { props.load(it) }
        }
        return props
    }

    companion object {
        private const val TAG = "ZeroUplink"
    }
}

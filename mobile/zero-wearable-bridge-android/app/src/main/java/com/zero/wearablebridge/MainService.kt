package com.zero.wearablebridge

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Foreground service that owns the [GlassesSession] + [ZeroUplink].
 * Lives for the lifetime of the pairing and surfaces a persistent
 * notification so the user always sees when Zero has eyes/ears on.
 */
class MainService : LifecycleService() {

    private val scope = CoroutineScope(Dispatchers.IO + Job())
    private lateinit var glasses: GlassesSession
    private var phoneFallback: PhoneCameraSession? = null
    private lateinit var uplink: ZeroUplink
    private lateinit var privacy: PrivacyState

    override fun onBind(intent: Intent): IBinder? {
        super.onBind(intent)
        return null
    }

    override fun onCreate() {
        super.onCreate()
        startForeground(NOTIFICATION_ID, buildNotification("Pairing with glasses…"))

        privacy = PrivacyState(this)
        uplink = ZeroUplink(this, privacy)
        glasses = GlassesSession(this, uplink, privacy)

        // Start the DAT-backed session first. When the AAR isn't present
        // (GlassesSession contains TODO(DAT) stubs that no-op today) we
        // transparently start the phone-camera fallback so frames + mic
        // still flow to Zero. This means the app is functional end-to-end
        // *right now* — no waiting on Meta's approval gate.
        scope.launch {
            glasses.start()
            uplink.start()

            // If DAT bound, glasses are the sensor. Otherwise the phone
            // camera takes over (controlled by `zero.fallback.phone` so a
            // user can force one or the other for testing).
            val props = java.util.Properties().apply {
                runCatching { assets.open("zero.properties").use { load(it) } }
            }
            val fallbackAllowed = props.getProperty("zero.fallback.phone", "true").toBoolean()
            if (glasses.isConnected) {
                updateNotification("Zero is watching (glasses)")
            } else if (fallbackAllowed) {
                phoneFallback = PhoneCameraSession(
                    this@MainService,
                    this@MainService,
                    uplink,
                    privacy,
                ).also { it.start() }
                updateNotification("Zero is watching (phone camera — no glasses paired)")
            } else {
                updateNotification("Zero not watching — pair glasses via Meta AI app")
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_PAUSE -> {
                privacy.setPaused(true)
                updateNotification("Paused (tap to resume)")
            }
            ACTION_RESUME -> {
                privacy.setPaused(false)
                updateNotification("Zero is watching")
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        try { phoneFallback?.stop() } catch (_: Throwable) {}
        scope.launch {
            glasses.stop()
            uplink.stop()
        }
        scope.cancel()
        super.onDestroy()
    }

    // ---- Notification helpers ---------------------------------------------

    private fun buildNotification(text: String): Notification {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            mgr.createNotificationChannel(
                NotificationChannel(CHANNEL, "Zero Wearable Bridge", NotificationManager.IMPORTANCE_LOW)
            )
        }
        return NotificationCompat.Builder(this, CHANNEL)
            .setContentTitle("Zero Wearable Bridge")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .setColor(0xFFE53935.toInt()) // red = eyes on
            .build()
    }

    private fun updateNotification(text: String) {
        val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        mgr.notify(NOTIFICATION_ID, buildNotification(text))
    }

    companion object {
        private const val CHANNEL = "zero-wearable-bridge"
        private const val NOTIFICATION_ID = 1001
        const val ACTION_PAUSE = "com.zero.wearablebridge.PAUSE"
        const val ACTION_RESUME = "com.zero.wearablebridge.RESUME"
    }
}

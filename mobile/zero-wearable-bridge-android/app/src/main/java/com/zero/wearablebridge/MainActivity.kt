package com.zero.wearablebridge

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
// Real class: com.meta.wearable.dat.core.Wearables — left as TODO below so
// the build ships without depending on SDK internals we haven't wired yet.

/**
 * Minimal settings / status screen. A real build would use Jetpack Compose
 * and bind to [PrivacyState]; this scaffold keeps the deps light so the
 * project compiles without Compose.
 */
class MainActivity : Activity() {

    private lateinit var statusView: TextView
    private lateinit var privacy: PrivacyState

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        privacy = PrivacyState(this)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 96, 48, 48)
        }

        statusView = TextView(this).apply { text = describeStatus() }
        root.addView(statusView)

        root.addView(Button(this).apply {
            text = "Pair with Ray-Ban Meta (one-time)"
            setOnClickListener { startRegistration() }
        })
        root.addView(Button(this).apply {
            text = "Start service"
            setOnClickListener { startBridge() }
        })
        root.addView(Button(this).apply {
            text = "Pause Zero"
            setOnClickListener {
                val i = Intent(this@MainActivity, MainService::class.java)
                    .setAction(MainService.ACTION_PAUSE)
                startService(i)
                statusView.text = describeStatus()
            }
        })
        root.addView(Button(this).apply {
            text = "Resume Zero"
            setOnClickListener {
                val i = Intent(this@MainActivity, MainService::class.java)
                    .setAction(MainService.ACTION_RESUME)
                startService(i)
                statusView.text = describeStatus()
            }
        })

        setContentView(root)
    }

    private fun startRegistration() {
        // TODO(DAT): call com.meta.wearable.dat.core.Wearables.initialize +
        // startRegistration here. The app runs fine without it via the
        // phone-camera fallback path in MainService.
        Log.i("MainActivity", "Pair tapped — DAT registration not yet wired")
    }

    private fun startBridge() {
        ensureRuntimePerms {
            val i = Intent(this, MainService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(i)
            } else {
                startService(i)
            }
            statusView.text = describeStatus()
        }
    }

    private fun ensureRuntimePerms(onGranted: () -> Unit) {
        val needed = mutableListOf<String>()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED) {
            needed.add(Manifest.permission.CAMERA)
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) {
            needed.add(Manifest.permission.RECORD_AUDIO)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
                needed.add(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
        if (needed.isEmpty()) {
            onGranted()
        } else {
            pendingGrant = onGranted
            ActivityCompat.requestPermissions(this, needed.toTypedArray(), REQ_PERMS)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQ_PERMS && grantResults.all { it == PackageManager.PERMISSION_GRANTED }) {
            pendingGrant?.invoke()
            pendingGrant = null
        }
    }

    private var pendingGrant: (() -> Unit)? = null

    companion object {
        private const val REQ_PERMS = 42
    }

    private fun describeStatus(): String {
        return buildString {
            appendLine("Zero Wearable Bridge")
            appendLine("Paused: ${privacy.isPaused()}")
            appendLine("Vision allowed now: ${privacy.visionAllowed()}")
            appendLine("Audio allowed now: ${privacy.audioAllowed()}")
        }
    }
}

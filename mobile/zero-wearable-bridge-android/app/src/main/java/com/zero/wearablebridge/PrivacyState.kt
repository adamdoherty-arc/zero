package com.zero.wearablebridge

import android.content.Context
import android.content.SharedPreferences
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import android.util.Log

/**
 * Single source of truth for privacy toggles. Every uplink call runs
 * through [visionAllowed] / [audioAllowed] first; if any of these is
 * false, nothing leaves the device.
 *
 * Toggles (persisted in SharedPreferences):
 *   - `paused` — hard kill switch. Default: false.
 *   - `vision_enabled`, `audio_enabled` — per-stream toggles.
 *   - `home_wifi_only` — only stream on the SSID in `home_ssid`.
 *   - `battery_saver` — when on + battery < 30%, drop to gesture-triggered frames.
 */
class PrivacyState(private val context: Context) {

    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun setPaused(paused: Boolean) {
        prefs.edit().putBoolean(KEY_PAUSED, paused).apply()
    }

    fun isPaused(): Boolean = prefs.getBoolean(KEY_PAUSED, false)

    fun visionAllowed(): Boolean =
        !isPaused() &&
            prefs.getBoolean(KEY_VISION, true) &&
            wifiOkay() &&
            batteryOkay()

    fun audioAllowed(): Boolean =
        !isPaused() &&
            prefs.getBoolean(KEY_AUDIO, true) &&
            wifiOkay() &&
            batteryOkay()

    private fun wifiOkay(): Boolean {
        if (!prefs.getBoolean(KEY_HOME_WIFI_ONLY, false)) return true
        val homeSsid = prefs.getString(KEY_HOME_SSID, null) ?: return false

        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return false
        val network = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(network) ?: return false
        if (!caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) return false

        val wifi = context.getSystemService(WifiManager::class.java) ?: return false
        val info = wifi.connectionInfo ?: return false
        val ssid = info.ssid?.trim('"') ?: return false
        return ssid.equals(homeSsid, ignoreCase = true)
    }

    private fun batteryOkay(): Boolean {
        if (!prefs.getBoolean(KEY_BATTERY_SAVER, false)) return true
        val bm = context.getSystemService(BatteryManager::class.java) ?: return true
        val level = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        if (level in 0..29) {
            Log.d(TAG, "battery saver active (level=$level) — suppressing stream")
            return false
        }
        return true
    }

    companion object {
        private const val TAG = "PrivacyState"
        private const val PREFS = "zero_privacy"
        private const val KEY_PAUSED = "paused"
        private const val KEY_VISION = "vision_enabled"
        private const val KEY_AUDIO = "audio_enabled"
        private const val KEY_HOME_WIFI_ONLY = "home_wifi_only"
        private const val KEY_HOME_SSID = "home_ssid"
        private const val KEY_BATTERY_SAVER = "battery_saver"
    }
}

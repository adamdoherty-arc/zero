package com.zero.wearablebridge

import android.content.Intent
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService

/** Quick-tile shortcut — one tap from the lock screen to pause/resume. */
class ZeroPauseTileService : TileService() {

    override fun onClick() {
        super.onClick()
        val privacy = PrivacyState(this)
        val nowPaused = !privacy.isPaused()
        privacy.setPaused(nowPaused)
        val intent = Intent(this, MainService::class.java)
            .setAction(if (nowPaused) MainService.ACTION_PAUSE else MainService.ACTION_RESUME)
        startService(intent)
        refreshTile()
    }

    override fun onStartListening() {
        super.onStartListening()
        refreshTile()
    }

    private fun refreshTile() {
        val tile = qsTile ?: return
        val paused = PrivacyState(this).isPaused()
        tile.state = if (paused) Tile.STATE_INACTIVE else Tile.STATE_ACTIVE
        tile.label = if (paused) "Zero: paused" else "Zero: watching"
        tile.updateTile()
    }
}

package com.zero.wearablebridge

import android.content.Context
import android.util.Log

/**
 * Pipes inbound TTS/text hints from Zero back to the wearer. Default impl
 * plays through the phone speaker via Android's built-in TextToSpeech; the
 * real build should instead hand off to the DAT SDK's audio-out so the
 * glasses' open-ear speaker speaks.
 */
class NotificationSink(private val context: Context) {

    suspend fun speak(text: String) {
        // TODO(DAT): route through session.speaker.play(pcm) instead of
        //            Android TextToSpeech. For now, log so integration
        //            tests in CI can assert delivery without real audio.
        Log.i(TAG, "speak → $text")
    }

    companion object {
        private const val TAG = "NotificationSink"
    }
}

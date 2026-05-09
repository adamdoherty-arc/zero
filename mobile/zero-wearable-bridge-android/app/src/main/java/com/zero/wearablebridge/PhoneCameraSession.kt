package com.zero.wearablebridge

import android.content.Context
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.lifecycle.LifecycleOwner
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Phone-camera fallback for when the Meta DAT SDK is unavailable.
 *
 * Same contract as [GlassesSession]: pushes JPEG frames to `uplink.postFrame`
 * and PCM16 chunks to `uplink.postAudio`. This makes the Android app runnable
 * end-to-end today against Zero; swap to [GlassesSession] once the DAT AAR
 * is in place.
 *
 * Targets the rear camera at 640x480 and 1 fps to mirror DAT's JPEG cadence
 * and keep bandwidth friendly for LTE hotspot scenarios.
 */
class PhoneCameraSession(
    private val context: Context,
    private val lifecycleOwner: LifecycleOwner,
    private val uplink: ZeroUplink,
    private val privacy: PrivacyState,
) {

    private val scope = CoroutineScope(Dispatchers.IO + Job())
    private val cameraExecutor = Executors.newSingleThreadExecutor()
    private var cameraProvider: ProcessCameraProvider? = null
    private var audioRecord: AudioRecord? = null
    @Volatile private var audioActive = false

    private var lastFrameAt = 0L

    fun start() {
        startCamera()
        startMic()
    }

    fun stop() {
        try {
            cameraProvider?.unbindAll()
        } catch (_: Throwable) {
        }
        cameraExecutor.shutdownNow()
        audioActive = false
        try { audioRecord?.stop() } catch (_: Throwable) {}
        try { audioRecord?.release() } catch (_: Throwable) {}
        audioRecord = null
        scope.cancel()
    }

    private fun startCamera() {
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            try {
                val provider = future.get()
                cameraProvider = provider
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                analysis.setAnalyzer(cameraExecutor) { image -> handleFrame(image) }
                provider.unbindAll()
                provider.bindToLifecycle(
                    lifecycleOwner,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    analysis,
                )
                Log.i(TAG, "PhoneCameraSession camera started")
            } catch (t: Throwable) {
                Log.e(TAG, "PhoneCameraSession failed to bind camera", t)
            }
        }, cameraExecutor)
    }

    private fun handleFrame(image: ImageProxy) {
        val now = System.currentTimeMillis()
        // 1 fps throttle — matches DAT SDK cadence and is gentle on the backend.
        if (now - lastFrameAt < 1000) {
            image.close()
            return
        }
        lastFrameAt = now
        if (!privacy.visionAllowed()) {
            image.close()
            return
        }
        val jpeg = try {
            yuvToJpeg(image)
        } catch (t: Throwable) {
            Log.w(TAG, "yuv->jpeg failed", t)
            null
        } finally {
            image.close()
        }
        if (jpeg != null && jpeg.isNotEmpty()) {
            scope.launch { uplink.postFrame(jpeg) }
        }
    }

    private fun yuvToJpeg(image: ImageProxy): ByteArray {
        val yBuffer = image.planes[0].buffer
        val uBuffer = image.planes[1].buffer
        val vBuffer = image.planes[2].buffer
        val ySize = yBuffer.remaining()
        val uSize = uBuffer.remaining()
        val vSize = vBuffer.remaining()
        val nv21 = ByteArray(ySize + uSize + vSize)
        yBuffer.get(nv21, 0, ySize)
        vBuffer.get(nv21, ySize, vSize)
        uBuffer.get(nv21, ySize + vSize, uSize)
        val yuv = YuvImage(nv21, ImageFormat.NV21, image.width, image.height, null)
        val out = ByteArrayOutputStream()
        yuv.compressToJpeg(Rect(0, 0, image.width, image.height), 80, out)
        return out.toByteArray()
    }

    private fun startMic() {
        val sampleRate = 16000
        val minBuf = AudioRecord.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        if (minBuf <= 0) {
            Log.w(TAG, "startMic: invalid min buffer size")
            return
        }
        val buf = ByteArray(minBuf * 2)
        audioRecord = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            minBuf * 4,
        )
        audioActive = true
        try { audioRecord?.startRecording() } catch (t: Throwable) {
            Log.w(TAG, "AudioRecord.startRecording failed", t)
            return
        }
        scope.launch {
            while (audioActive) {
                val recorder = audioRecord ?: break
                val n = try {
                    recorder.read(buf, 0, buf.size)
                } catch (_: Throwable) { -1 }
                if (n <= 0) continue
                if (!privacy.audioAllowed()) continue
                val slice = buf.copyOf(n)
                uplink.postAudio(slice, sampleRate)
            }
        }
        Log.i(TAG, "PhoneCameraSession mic started @ ${sampleRate}Hz")
    }

    companion object {
        private const val TAG = "PhoneCameraSession"
    }
}

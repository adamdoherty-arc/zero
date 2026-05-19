from zero.bifrost import chat_stream  # Add import
from zero.llm.unified_client import UnifiedLLMClient

class VoiceLoopService:
    def __init__(self):
        self.llm_client = UnifiedLLMClient()
    
    async def stream_audio(self, audio_input: bytes) -> AsyncGenerator[bytes, None]:
        # Original audio streaming logic wrapped
        async def _audio_generator():
            # Simulated audio processing
            for chunk in audio_input.split():
                yield chunk
        
        # Double-wrap with chat_stream
        return chat_stream(_audio_generator())
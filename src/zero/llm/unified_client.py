from typing import AsyncGenerator, Dict, Any
from zero.bifrost import chat_stream  # Add import

class UnifiedLLMClient:
    async def stream_response(self, prompt: str) -> AsyncGenerator[Dict[str, Any], None]:
        # Original generator logic
        async def _generator():
            # Simulated streaming logic
            for i in range(5):
                yield {"chunk": f"Part {i}"}
        
        # Wrap with chat_stream
        return chat_stream(_generator())
import asyncio
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class AssistantResponse:
    text: str
    metadata: Dict[str, Any]
    timestamp: datetime

class AssistantService:
    def __init__(self, llm_client=None, memory_store=None):
        self.llm_client = llm_client
        self.memory_store = memory_store
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the assistant service."""
        if self._initialized:
            return True
        
        try:
            if self.llm_client:
                await self.llm_client.connect()
            if self.memory_store:
                await self.memory_store.connect()
            self._initialized = True
            logger.info("AssistantService initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize AssistantService: {e}")
            raise

    async def process_query(self, query: str, user_id: str = "default") -> AssistantResponse:
        """Process a user query and return a response."""
        if not self._initialized:
            await self.initialize()
        
        # Get context from memory
        context = {}
        if self.memory_store:
            context = await self.memory_store.get_context(user_id)
        
        # Generate response using LLM
        if self.llm_client:
            response_text = await self.llm_client.generate(query, context)
        else:
            response_text = f"Processed: {query}"
        
        # Save to memory
        if self.memory_store:
            await self.memory_store.save_context(user_id, {**context, "last_query": query})
        
        return AssistantResponse(
            text=response_text,
            metadata={"user_id": user_id, "has_llm": self.llm_client is not None},
            timestamp=datetime.now()
        )

    async def get_status(self) -> Dict[str, Any]:
        """Get the current status of the assistant service."""
        status = {
            "initialized": self._initialized,
            "has_llm": self.llm_client is not None,
            "has_memory": self.memory_store is not None,
            "timestamp": datetime.now().isoformat()
        }
        
        if self.llm_client:
            status["llm_status"] = getattr(self.llm_client, "status", "unknown")
        
        if self.memory_store:
            status["memory_status"] = getattr(self.memory_store, "status", "unknown")
        
        return status

    async def shutdown(self) -> None:
        """Shutdown the assistant service."""
        if self.llm_client:
            await self.llm_client.disconnect()
        if self.memory_store:
            await self.memory_store.disconnect()
        self._initialized = False
        logger.info("AssistantService shut down")
import asyncio
import logging
from typing import Any, Dict, List, Optional

from ..config import settings
from ..models import AgentState, Message
from ..repositories import AgentRepository
from ..clients import LLMClient, VectorDBClient
from ..utils import parse_json_response

logger = logging.getLogger(__name__)

class AgentService:
    def __init__(
        self,
        agent_repo: AgentRepository,
        llm_client: LLMClient,
        vector_db: VectorDBClient,
    ):
        self.agent_repo = agent_repo
        self.llm_client = llm_client
        self.vector_db = vector_db

    async def initialize_agent(self, agent_id: str) -> AgentState:
        """Initialize or retrieve an agent's state."""
        agent = await self.agent_repo.get_agent(agent_id)
        if not agent:
            agent = await self.agent_repo.create_agent(agent_id)
        await self.vector_db.ensure_collection(agent_id)
        return agent

    async def process_message(self, agent_id: str, message: Message) -> Dict[str, Any]:
        """Process an incoming message and return the response."""
        agent = await self.initialize_agent(agent_id)
        
        # Retrieve context from vector DB
        context = await self.vector_db.query(agent_id, message.content)
        
        # Generate response using LLM
        llm_response = await self.llm_client.generate(
            prompt=message.content,
            context=context,
            agent_state=agent.state,
        )
        
        # Parse and store response
        parsed = parse_json_response(llm_response)
        await self.agent_repo.update_state(agent_id, parsed.get("state", agent.state))
        
        return {
            "agent_id": agent_id,
            "response": parsed.get("response", llm_response),
            "context_used": len(context),
            "new_state": parsed.get("state", agent.state),
        }

    async def get_agent_history(self, agent_id: str, limit: int = 50) -> List[Message]:
        """Retrieve message history for an agent."""
        return await self.agent_repo.get_messages(agent_id, limit=limit)

    async def reset_agent(self, agent_id: str) -> bool:
        """Reset an agent's state and clear temporary data."""
        await self.agent_repo.reset_state(agent_id)
        await self.vector_db.clear_temp(agent_id)
        return True

    async def export_agent_data(self, agent_id: str) -> Dict[str, Any]:
        """Export all data for an agent."""
        agent = await self.agent_repo.get_agent(agent_id)
        history = await self.get_agent_history(agent_id)
        context = await self.vector_db.query(agent_id, "")
        
        return {
            "agent_id": agent_id,
            "state": agent.state,
            "message_count": len(history),
            "context_entries": len(context),
            "exported_at": asyncio.get_event_loop().time(),
        }
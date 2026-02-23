from enum import Enum
from typing import Optional
from app.enums.execution_strategy import ExecutionStrategy

class LegionIntegrationService:
    """Service class for handling signals and returning appropriate execution strategies."""
    
    def handle_signal(self, signal_type: str) -> ExecutionStrategy:
        """Handle a signal and return the appropriate ExecutionStrategy."""
        strategy_map = {
            'start': ExecutionStrategy.START,
            'stop': ExecutionStrategy.STOP,
            'pause': ExecutionStrategy.PAUSE,
            'resume': ExecutionStrategy.RESUME,
            'restart': ExecutionStrategy.RESTART,
        }
        if signal_type in strategy_map:
            return strategy_map[signal_type]
        else:
            raise ValueError(f"Unknown signal type: {signal_type}")
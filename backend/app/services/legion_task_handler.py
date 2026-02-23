import logging
from legion_client import create_task

class LegionTaskHandler:
    """Service class for handling Legion task creation and validation."""
    
    def __init__(self):
        """Initialize the handler with a logger."""
        self.logger = logging.getLogger('legion_task_handler')
        self.logger.setLevel(logging.INFO)
        
    def validate_signal_type(self, signal_type):
        """Validate that the signal type is one of the allowed types."""
        allowed_types = ['signal1', 'signal2', 'signal3']
        if signal_type not in allowed_types:
            raise ValueError(f"Invalid signal type: {signal_type}. Allowed types: {allowed_types}")
        return True

    def create_legion_task(self, signal_type, **kwargs):
        """Create a Legion task with the given signal type and metadata."""
        self.validate_signal_type(signal_type)
        task_definition = {
            'signal_type': signal_type,
            'metadata': kwargs
        }
        task_id = create_task(task_definition)
        self.log_task_creation_metadata(task_id, signal_type, kwargs)
        return task_id

    def log_task_creation_metadata(self, task_id, signal_type, metadata):
        """Log metadata about the created task."""
        self.logger.info(f"Created task {task_id} for signal type {signal_type} with metadata: {metadata}")

__all__ = ['LegionTaskHandler']
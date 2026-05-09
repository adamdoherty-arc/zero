import logging
import json
import threading
from json_log_formatter import JsonFormatter
from uuid import uuid4

# Thread-local storage for correlation IDs
thread_local = threading.local()

def get_correlation_id():
    """Retrieve or generate a correlation ID for the current context"""
    if not hasattr(thread_local, 'correlation_id'):
        thread_local.correlation_id = str(uuid4())
    return thread_local.correlation_id

class CorrelationIdFilter(logging.Filter):
    """Add correlation ID to log records"""
    def filter(self, record):
        record.correlation_id = get_correlation_id()
        return True

def configure_logging():
    """Configure structured logging with correlation IDs and severity levels"""
    # Create root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # Create console handler
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    
    # Create formatter with structured output
    formatter = JsonFormatter(
        keys_order=[
            'timestamp', 
            'level', 
            'correlation_id', 
            'message', 
            'severity', 
            'exception'
        ],
        json_indent=2
    )
    
    # Add formatter and filter to handler
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationIdFilter())
    
    # Add handler to logger
    logger.addHandler(handler)
    
    return logger

def test_logging():
    """Test logging with different severity levels and error scenarios"""
    logger = logging.getLogger(__name__)
    
    # Test normal log with correlation ID
    logger.info("This is a test info message")
    
    # Test different severity levels
    logger.debug("Debug message (low severity)")
    logger.warning("Warning message (medium severity)")
    logger.error("Error message (high severity)")
    
    # Test error with exception
    try:
        1 / 0
    except Exception:
        logger.exception("Division by zero - critical error (highest severity)")
    
    # Verify correlation ID persistence
    assert hasattr(thread_local, 'correlation_id'), "Correlation ID not set"
    print(f"\nTest complete. Correlation ID used: {get_correlation_id()}")

if __name__ == "__main__":
    configure_logging()
    test_logging()
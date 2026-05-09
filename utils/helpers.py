import logging

logger = logging.getLogger(__name__)

def validate_data(data):
    if not data:
        logger.warning("Empty data provided", extra={"context": "validation"})
        return False
    
    if not isinstance(data, dict):
        logger.error("Invalid data type", extra={"expected_type": "dict", "actual_type": type(data).__name__})
        return False
        
    logger.debug("Data validation passed", extra={"data_keys": list(data.keys())})
    return True
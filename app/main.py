import logging
import os
from zero.core import ZeroAssistant

logger = logging.getLogger(__name__)

def main():
    logger.info("Starting Zero Personal Assistant", extra={"environment": os.getenv("ENV", "development")})
    
    try:
        assistant = ZeroAssistant()
        logger.info("Loading configuration", extra={"config_path": assistant.config_path})
        assistant.load_configuration()
        logger.info("Configuration loaded successfully", extra={"config_version": assistant.config_version})
        
        logger.info("Initializing services", extra={"services": assistant.services})
        assistant.initialize_services()
        
        logger.info("Starting main loop")
        assistant.run()
        
    except Exception as e:
        logger.error("Critical error in main loop", exc_info=True, extra={"error": str(e)})
        raise

if __name__ == "__main__":
    main()
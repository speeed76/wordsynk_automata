# filename: main.py
from services.crawler_service import CrawlerService
from logger import get_logger
from config import DB_PATH # Ensure DB_PATH is used from config

logger = get_logger(__name__)

def main():
    logger.info("--- Starting Booking Crawler Application ---")
    # TEST_MODE True will reset the database each run. False will append.
    # Set target_display_name to "internal" or specific virtual display name
    # if needed, or None to let DisplayManager try to autodetect.
    crawler = None
    try:
        crawler = CrawlerService(db_path=DB_PATH, test_mode=False, target_display_name=None)
        crawler.run()
    except Exception as e:
        logger.exception(f"An unhandled exception occurred in main: {e}")
    finally:
        if crawler: # Ensure cleanup is called if crawler was initialized
            logger.info("Ensuring cleanup in main's finally block.") # Should be handled by crawler.run's finally
        logger.info("--- Booking Crawler Application Finished ---")

if __name__ == "__main__":
    main()
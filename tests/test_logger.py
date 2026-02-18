from src.utils import setup_logger
import os

def test_logging():
    logger = setup_logger("TestLogger")
    logger.info("This is a test log message to verify file logging.")

    log_path = os.path.join("logs", "NewsFeed_log.log")
    if os.path.exists(log_path):
        print(f"Success: Log file created at {log_path}")
        with open(log_path, 'r') as f:
            content = f.read()
            print(f"Log content: {content.strip()}")
    else:
        print("Failure: Log file not created.")

if __name__ == "__main__":
    test_logging()

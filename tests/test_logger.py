from src.utils import setup_logger
import os

def test_logging():
    log_dir = "logs"
    logger = setup_logger("TestLogger", log_dir=log_dir)
    logger.info("This is a test log message to verify file logging.")

    # Find the most recent log file
    import glob
    log_files = glob.glob(os.path.join(log_dir, "app_*.log"))
    if log_files:
        log_path = max(log_files, key=os.path.getmtime)
        print(f"Success: Log file created at {log_path}")
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if "This is a test log message" in content:
                print(f"Log content verified.")
            else:
                print("Failure: Log message not found in file.")
    else:
        print("Failure: No log file found.")

if __name__ == "__main__":
    test_logging()

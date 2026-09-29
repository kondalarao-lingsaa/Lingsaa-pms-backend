import time
import logging
import functools
from local.logging_config import performence_logger
# Configure logger
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger("performance")

def measure_time(func):
    """Decorator to measure execution time of a function"""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()  # Start timer
        result = await func(*args, **kwargs)  # Call the actual function
        end_time = time.time()  # End timer
        duration = round(end_time - start_time, 2)  # Convert to milliseconds
        performence_logger.info(f"Function '{func.__name__}' executed in {duration}seconds")
        return result
    return wrapper

def measure_time_sync(func):
    """Decorator to measure execution time of a synchronous function in seconds"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()  # Start timer
        result = func(*args, **kwargs)  # Call the actual synchronous function
        end_time = time.time()  # End timer
        duration = round(end_time - start_time, 2)  # Time in seconds, rounded to 2 decimal places
        performence_logger.info(f"Function '{func.__name__}' executed in {duration} seconds")
        return result
    return wrapper

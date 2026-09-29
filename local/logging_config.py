# import logging.config
# import yaml
# import os
# print('current index is',os.getcwd())
# from datetime import datetime
# import sys
# # sys.path.append('C:/Users/karthik/Documents/wetradersweb_to_api/wetraders_be/logging.yaml')

# # Load logging configuration from YAML
# with open("logging.yaml", "r") as file:
#     config = yaml.safe_load(file)

# # Get today's date and create a daily log directory
# today = datetime.today().strftime('%Y-%m-%d')
# log_dir = f"wetraders_logs/{today}"
# os.makedirs(log_dir, exist_ok=True)

# # Update log file paths dynamically
# config['handlers']['access_file']['filename'] = f"{log_dir}/access.log"
# config['handlers']['error_file']['filename'] = f"{log_dir}/error.log"
# config['handlers']['out_file']['filename'] = f"{log_dir}/out.log"

# # Apply the logging configuration
# logging.config.dictConfig(config)

# # Get loggers
# access_logger = logging.getLogger("access")
# error_logger = logging.getLogger("error")
# out_logger = logging.getLogger("out")
# performence_logger = logging.getLogger("performence")

import logging.config
import yaml
import os
from datetime import datetime

# Load logging configuration from YAML
with open("logging.yaml", "r") as file:
    config = yaml.safe_load(file)

# Global variable to track current log directory date
current_log_date = None

def update_log_directory():
    """Creates today's log folder and updates log file paths dynamically."""
    global current_log_date

    today = datetime.today().strftime('%Y-%m-%d')

    # Skip update if date hasn't changed
    if today == current_log_date:
        return

    current_log_date = today
    log_dir = f"wetraders_logs/{today}"
    os.makedirs(log_dir, exist_ok=True)  # Ensure today's folder exists

    # Update log file paths dynamically in config
    config['handlers']['access_file']['filename'] = f"{log_dir}/access.log"
    config['handlers']['error_file']['filename'] = f"{log_dir}/error.log"
    config['handlers']['out_file']['filename'] = f"{log_dir}/out.log"

    # Apply updated logging configuration
    logging.config.dictConfig(config)

class DailyLogUpdateFilter(logging.Filter):
    """A logging filter that updates the log directory if date changes."""
    def filter(self, record):
        update_log_directory()
        return True

# Apply initial configuration
update_log_directory()

# Get loggers
access_logger = logging.getLogger("access")
error_logger = logging.getLogger("error")
out_logger = logging.getLogger("out")
performence_logger = logging.getLogger("performence")

# Add the dynamic filter to each logger
for logger in [access_logger, error_logger, out_logger, performence_logger]:
    for handler in logger.handlers:
        handler.addFilter(DailyLogUpdateFilter())


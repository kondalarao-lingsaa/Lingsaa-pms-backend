import sys
# sys.path.append('/var/www/html/algotrader/algo_backend')
sys.path.append('C:/Users/arunkumar/Desktop/projects/LINGSAA_PROJECTMANAGEMENT')
from dotenv import load_dotenv
load_dotenv('C:/Users/arunkumar/Desktop/projects/LINGSAA_PROJECTMANAGEMENT/local/dev.env')
# load_dotenv('C:/Users/karthik/Documents/wetraders  web to api/wetraders_be/local/dev.env')
import os
print('sql is -->',os.environ.get('sql'))
from local.init import app
import uvicorn
from constants import BaseConstants
import os
import asyncio
import logging

background_task_instance = []

@app.on_event("startup")
async def startup_event():
    global background_task_instance
    print("🚀 App startup")
    # Example: background_task_instance.append(asyncio.create_task(some_task()))

@app.on_event("shutdown")
async def shutdown_event():
    print("🧹 Closing background tasks")

    if background_task_instance:
        for task in background_task_instance:
            task.cancel()

    print("✅ All background tasks closed.")


import threading

if __name__ == "__main__":

    if threading.current_thread() is threading.main_thread():
        print("Running in the main thread.")

        uvicorn.run(app, host="127.0.0.1", port=8000)
    else:
        print("Not in the main thread.") 



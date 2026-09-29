from fastapi import FastAPI
from contextlib import asynccontextmanager
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 App startup: starting background task...")

    #task = asyncio.create_task(delta_hist_data())  # Run in background

    yield  # 🟢 This allows FastAPI to start serving routes

    print("🧹 App shutdown: cancelling background task...")
    #task.cancel()
    try:
        #await task
        print("✔️ Background task completed.")
    except asyncio.CancelledError:
        print("✔️ Background task cancelled cleanly.")


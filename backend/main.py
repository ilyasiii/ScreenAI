"""
Screen Reader AI - Backend Server
FastAPI backend that receives screenshots, maintains context,
and uses OpenAI GPT-4.1 Vision to analyze and answer questions.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pathlib import Path
from contextlib import asynccontextmanager
import asyncio
import os

# Load .env from the backend directory regardless of cwd
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

from routers import analyze
from routers import voice
from services.context_manager import context_manager


async def _cleanup_loop():
    """Background task: remove idle sessions every hour to free memory."""
    while True:
        await asyncio.sleep(3600)
        removed = context_manager.cleanup_old_sessions()
        if removed:
            print(f"[cleanup] Removed {removed} idle session(s)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_cleanup_loop())
    yield


app = FastAPI(
    title="Screen Reader AI",
    description="AI-powered screen reading and question answering",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(analyze.router, prefix="/api")
app.include_router(voice.router)


@app.get("/")
async def root():
    return {"message": "Screen Reader AI Backend is running", "version": "1.0.0"}


@app.get("/health")
async def health():
    api_key = os.getenv("OPENAI_API_KEY", "")
    has_key = bool(api_key and api_key != "sk-your-api-key-here")
    return {
        "status": "healthy",
        "openai_configured": has_key,
        "model": os.getenv("OPENAI_MODEL", "gpt-4.1"),
    }

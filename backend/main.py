"""
Screen Reader AI - Backend Server
FastAPI backend that receives screenshots, maintains context,
and uses OpenAI GPT-4o Vision to analyze and answer questions.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from pathlib import Path
import os

# Load .env from the backend directory regardless of cwd
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

from routers import analyze

app = FastAPI(
    title="Screen Reader AI",
    description="AI-powered screen reading and question answering",
    version="1.0.0",
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


@app.get("/")
async def root():
    return {"message": "Screen Reader AI Backend is running", "version": "1.0.0"}


@app.get("/health")
async def health():
    api_key = os.getenv("GEMINI_API_KEY", "")
    has_key = bool(api_key and api_key != "your-gemini-api-key-here")
    return {
        "status": "healthy",
        "ai_configured": has_key,
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    }

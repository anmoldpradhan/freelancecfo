from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.auth import router as auth_router
from app.api.v1.transaction import router as transactions_router

app = FastAPI(
    title="FreelanceCFO API",
    description="AI-powered financial management for freelancers",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(transactions_router)

@app.get("/health", tags=["system"])
async def health_check():
    """Confirms the API is running. CI and load balancers ping this."""
    return {"status": "ok", "service": "freelancecfo-api"}
from fastapi import FastAPI
from routes import reel

app = FastAPI(
    title="ReelMate API",
    description="AI Reel Coaching Backend",
    version="1.0.0"
)

app.include_router(reel.router)

@app.get("/health")
def health():
    return {"status": "ok", "message": "ReelMate API is running"}

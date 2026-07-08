"""ModelForge 2.0 FastAPI Backend."""
from fastapi import FastAPI

app = FastAPI(title="ModelForge", version="2.0")


@app.get("/")
async def root():
    """Root endpoint returning service info."""
    return {"name": "ModelForge", "version": "2.0"}

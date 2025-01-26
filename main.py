from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import json

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

@app.get("/")
async def root():
    return {"message": "Resume Processor API is running"}

@app.post("/process-resume/")
async def process_resume(
    file: UploadFile = File(...),
    job_description: str = None
):
    try:
        # Read the file content
        content = await file.read()
        
        # For now, just return a simple response
        # We'll add more processing logic later
        return {
            "message": "Resume received successfully",
            "filename": file.filename,
            "job_description": job_description
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

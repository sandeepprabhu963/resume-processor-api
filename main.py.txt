from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import docx2txt
import spacy
import json
from typing import Dict

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with your frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class JobDescription(BaseModel):
    text: str

@app.get("/")
async def read_root():
    return {"status": "healthy", "message": "Resume Processor API is running"}

@app.post("/process-resume/")
async def process_resume(file: UploadFile = File(...), job_description: str = None):
    try:
        # Read the uploaded file
        content = await file.read()
        
        # Process the resume
        resume_text = docx2txt.process(content)
        
        # Load spaCy model
        nlp = spacy.load("en_core_web_sm")
        
        # Process both texts
        doc_resume = nlp(resume_text)
        doc_job = nlp(job_description) if job_description else None
        
        # Extract key information (customize this based on your needs)
        processed_content = {
            "extracted_text": resume_text,
            "entities": [
                {"text": ent.text, "label": ent.label_}
                for ent in doc_resume.ents
            ],
            # Add more processing as needed
        }
        
        return processed_content
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
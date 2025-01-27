from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from docx import Document
from docxtpl import DocxTemplate
import google.generativeai as genai
import json
import os
from io import BytesIO
from typing import Dict, Any
from dotenv import load_dotenv
from datetime import datetime
import re
from supabase import create_client

load_dotenv()

app = FastAPI()

# Configure CORS with more specific settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
    expose_headers=["Content-Disposition"],  # Important for file downloads
)

# ... keep existing code (API key configuration and Supabase client initialization)

def docx_to_json(doc: Document) -> Dict[str, str]:
    # ... keep existing code (docx to json conversion function)

def optimize_with_gemini(json_data: Dict[str, str], job_description: str) -> Dict[str, str]:
    # ... keep existing code (Gemini optimization function)

def json_to_docx(template_doc: DocxTemplate, json_data: Dict[str, str]) -> BytesIO:
    # ... keep existing code (json to docx conversion function)

@app.post("/process-resume/")
async def process_resume(
    file: UploadFile = File(...),
    job_description: str = Form(...)
) -> StreamingResponse:
    try:
        if not file.filename.endswith('.docx'):
            raise HTTPException(
                status_code=400,
                detail="Invalid file format. Please upload a .docx file."
            )

        print(f"Processing resume: {file.filename}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Read and process the document
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(
                status_code=400,
                detail="Empty file uploaded"
            )
        
        # Create Document objects
        doc = Document(BytesIO(content))
        template_doc = DocxTemplate(BytesIO(content))
        
        # Process the resume
        json_data = docx_to_json(doc)
        optimized_json = optimize_with_gemini(json_data, job_description)
        output = json_to_docx(template_doc, optimized_json)
        
        # Store files in Supabase and create record
        try:
            filename = re.sub(r'[^\w\-\.]', '_', file.filename).strip('_').strip()
            
            # Save original JSON
            original_json_path = f"original_{timestamp}_{filename}.json"
            json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
            json_bytes = json_str.encode('utf-8')
            supabase.storage.from_("resume_templates").upload(
                original_json_path,
                json_bytes
            )
            
            # Save optimized JSON
            optimized_json_path = f"optimized_{timestamp}_{filename}.json"
            optimized_json_str = json.dumps(optimized_json, ensure_ascii=False, indent=2)
            optimized_json_bytes = optimized_json_str.encode('utf-8')
            supabase.storage.from_("resume_templates").upload(
                optimized_json_path,
                optimized_json_bytes
            )
            
            # Store optimization record
            supabase.table('resume_optimizations').insert({
                'original_resume_path': original_json_path,
                'optimized_resume_path': optimized_json_path,
                'job_description': job_description,
                'status': 'completed'
            }).execute()
            
        except Exception as e:
            print(f"Supabase storage error: {str(e)}")
            # Continue even if storage fails
        
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename=optimized_{filename}",
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )
        
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Processing error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

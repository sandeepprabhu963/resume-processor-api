from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from docx import Document
from docxtpl import DocxTemplate
from openai import OpenAI
import json
import os
from io import BytesIO
from typing import Dict, Any
from dotenv import load_dotenv
from datetime import datetime
import base64
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="Resume Optimizer API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600,
)

# Initialize OpenAI client
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is not set")

client = OpenAI(
    api_key=api_key,
    base_url="https://api.openai.com/v1",
    timeout=60.0,
    max_retries=2
)

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not supabase_url or not supabase_key:
    raise ValueError("Supabase environment variables are not set")

supabase: Client = create_client(supabase_url, supabase_key)

def extract_template_variables(doc: Document) -> Dict[str, str]:
    """Extract template variables from the document."""
    variables = {}
    for paragraph in doc.paragraphs:
        text = paragraph.text
        # Look for potential template variables (text between {{ and }})
        if "{{" in text and "}}" in text:
            var_start = text.find("{{")
            var_end = text.find("}}")
            var_name = text.strip()[var_start+2:var_end].strip()
            variables[var_name] = ""
    return variables

def optimize_resume_content(resume_text: str, job_description: str) -> Dict[str, str]:
    """Use OpenAI to optimize resume content based on job description."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """You are a professional resume optimizer. Analyze the resume content 
                    and job description to enhance the resume while maintaining the exact same structure 
                    and format. Return a JSON object with the optimized content for each section."""
                },
                {
                    "role": "user",
                    "content": f"Resume:\n{resume_text}\n\nJob Description:\n{job_description}"
                }
            ],
            temperature=0.3
        )
        
        optimized_content = response.choices[0].message.content
        return json.loads(optimized_content)
    except Exception as e:
        print(f"OpenAI optimization error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to optimize resume: {str(e)}")

@app.post("/process-resume/")
async def process_resume(
    file: UploadFile = File(...),
    job_description: str = Form(...)
):
    try:
        print(f"Processing resume: {file.filename}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Read the original document
        content = await file.read()
        
        # Store original resume in Supabase Storage
        original_file_path = f"original_{timestamp}_{file.filename}"
        storage_response = supabase.storage.from_("resume_templates").upload(
            original_file_path,
            content
        )
        print(f"Original resume stored: {original_file_path}")
        
        # Store job description
        jd_file_path = f"jd_{timestamp}.txt"
        jd_bytes = job_description.encode('utf-8')
        supabase.storage.from_("resume_templates").upload(
            jd_file_path,
            jd_bytes
        )
        print(f"Job description stored: {jd_file_path}")
        
        # Process the document
        doc = Document(BytesIO(content))
        template_doc = DocxTemplate(BytesIO(content))
        
        # Extract template variables and current content
        variables = extract_template_variables(doc)
        current_content = "\n".join([p.text for p in doc.paragraphs])
        
        # Optimize content using OpenAI
        optimized_variables = optimize_resume_content(current_content, job_description)
        
        # Render template with optimized content
        template_doc.render(optimized_variables)
        
        # Save optimized document
        output = BytesIO()
        template_doc.save(output)
        output.seek(0)
        
        # Store optimized resume
        optimized_file_path = f"optimized_{timestamp}_{file.filename}"
        supabase.storage.from_("resume_templates").upload(
            optimized_file_path,
            output.getvalue()
        )
        print(f"Optimized resume stored: {optimized_file_path}")
        
        # Return the optimized document
        output.seek(0)
        headers = {
            "Content-Disposition": f"attachment; filename=optimized_{file.filename}",
            "Access-Control-Expose-Headers": "Content-Disposition",
            "Access-Control-Allow-Origin": "*"
        }
        
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=headers
        )
        
    except Exception as e:
        print(f"Error processing resume: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.options("/process-resume/")
async def options_process_resume():
    return {
        "allow": "POST,OPTIONS",
        "content-type": "multipart/form-data",
        "access-control-allow-headers": "Content-Type,Authorization",
        "access-control-allow-origin": "*"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        workers=1,
        log_level="info"
    )

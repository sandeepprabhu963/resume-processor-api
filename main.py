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
import re

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

if not supabase_url:
    raise ValueError("SUPABASE_URL environment variable is not set")
if not supabase_key:
    raise ValueError("SUPABASE_SERVICE_ROLE_KEY environment variable is not set")

try:
    print(f"Initializing Supabase client with URL: {supabase_url}")
    supabase = create_client(supabase_url, supabase_key)
except Exception as e:
    print(f"Error initializing Supabase client: {str(e)}")
    raise ValueError(f"Failed to initialize Supabase client: {str(e)}")

def sanitize_filename(filename: str) -> str:
    """Sanitize filename to be safe for storage."""
    # Remove square brackets and their contents
    filename = re.sub(r'\[.*?\]', '', filename)
    # Replace any non-alphanumeric characters (except dots and hyphens) with underscores
    filename = re.sub(r'[^\w\-\.]', '_', filename)
    # Remove any leading/trailing spaces or underscores
    filename = filename.strip('_').strip()
    return filename

def extract_template_variables(doc: Document) -> Dict[str, str]:
    """Extract template variables from the document."""
    variables = {}
    for paragraph in doc.paragraphs:
        text = paragraph.text
        if "{{" in text and "}}" in text:
            var_start = text.find("{{")
            var_end = text.find("}}")
            var_name = text.strip()[var_start+2:var_end].strip()
            variables[var_name] = ""
    return variables

def optimize_resume_content(resume_text: str, job_description: str) -> Dict[str, str]:
    """Use OpenAI to optimize resume content based on job description."""
    try:
        print("Sending request to OpenAI for resume optimization...")
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": """You are an expert ATS-optimized resume writer. Your task is to:

1. Analyze the job description thoroughly to identify:
   - Key technical skills and tools required
   - Soft skills and qualifications needed
   - Core responsibilities and deliverables
   - Industry-specific keywords and terminology

2. Review the resume content and:
   - Highlight experiences that directly match job requirements
   - Incorporate identified keywords naturally into bullet points
   - Quantify achievements where possible (%, $, numbers)
   - Use strong action verbs aligned with job responsibilities
   - Ensure technical terms match those in the job description
   - Maintain professional tone and clarity

3. Important formatting rules:
   - Keep the EXACT same structure as the original resume
   - Maintain all section headings exactly as they appear
   - Preserve all dates, company names, and titles
   - Return a valid JSON where each key matches original sections
   - Ensure proper formatting with correct punctuation
   - Keep education details unchanged

4. Focus on:
   - Making each bullet point directly relevant to the job
   - Using industry-standard terminology from the job post
   - Highlighting transferable skills when direct experience is missing
   - Maintaining clear, concise language
   - Ensuring ATS-friendly formatting

Output must be a properly formatted JSON object where:
- Each key exactly matches a section from the original resume
- Each value contains the optimized content for that section
- All formatting and structure remain identical to the original"""
                },
                {
                    "role": "user",
                    "content": f"""Original Resume:
                    {resume_text}
                    
                    Job Description:
                    {job_description}
                    
                    Please optimize this resume for the job while maintaining its exact structure and format."""
                }
            ],
            temperature=0.7,
            max_tokens=2500
        )
        
        optimized_content = response.choices[0].message.content
        print("Received response from OpenAI, attempting to parse JSON...")
        
        try:
            parsed_content = json.loads(optimized_content)
            return parsed_content
        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {str(e)}")
            print(f"Failed to parse content: {optimized_content}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to parse optimization result: {str(e)}"
            )
            
    except Exception as e:
        print(f"OpenAI optimization error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to optimize resume: {str(e)}"
        )

@app.post("/process-resume/")
async def process_resume(
    file: UploadFile = File(...),
    job_description: str = Form(...)
):
    try:
        print(f"Processing resume: {file.filename}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Sanitize the filename
        sanitized_filename = sanitize_filename(file.filename)
        print(f"Sanitized filename: {sanitized_filename}")
        
        # Read the original document
        content = await file.read()
        
        # Store original resume in Supabase Storage
        original_file_path = f"original_{timestamp}_{sanitized_filename}"
        try:
            storage_response = supabase.storage.from_("resume_templates").upload(
                original_file_path,
                content
            )
            print(f"Original resume stored: {original_file_path}")
        except Exception as e:
            print(f"Storage error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to store original resume: {str(e)}")
        
        # Store job description
        jd_file_path = f"jd_{timestamp}.txt"
        jd_bytes = job_description.encode('utf-8')
        try:
            supabase.storage.from_("resume_templates").upload(
                jd_file_path,
                jd_bytes
            )
            print(f"Job description stored: {jd_file_path}")
        except Exception as e:
            print(f"Failed to store job description: {str(e)}")
            # Continue processing even if job description storage fails
        
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
        optimized_file_path = f"optimized_{timestamp}_{sanitized_filename}"
        try:
            supabase.storage.from_("resume_templates").upload(
                optimized_file_path,
                output.getvalue()
            )
            print(f"Optimized resume stored: {optimized_file_path}")
        except Exception as e:
            print(f"Failed to store optimized resume: {str(e)}")
            # Continue to return the optimized document even if storage fails
        
        # Return the optimized document
        output.seek(0)
        headers = {
            "Content-Disposition": f"attachment; filename=optimized_{sanitized_filename}",
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

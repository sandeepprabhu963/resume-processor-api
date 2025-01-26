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

if not supabase_url or not supabase_key:
    raise ValueError("Supabase environment variables are not properly set")

try:
    supabase = create_client(supabase_url, supabase_key)
except Exception as e:
    print(f"Error initializing Supabase client: {str(e)}")
    raise ValueError(f"Failed to initialize Supabase client: {str(e)}")

def sanitize_filename(filename: str) -> str:
    """Sanitize filename to be safe for storage."""
    filename = re.sub(r'\[.*?\]', '', filename)
    filename = re.sub(r'[^\w\-\.]', '_', filename)
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
            var_name = text[var_start+2:var_end].strip()
            variables[var_name] = ""
    return variables

def optimize_resume_content(resume_text: str, job_description: str) -> Dict[str, str]:
    """Use OpenAI to optimize resume content based on job description."""
    try:
        print("Sending request to OpenAI for resume optimization...")
        
        # Enhanced system prompt for better resume optimization
        system_prompt = """You are an expert ATS resume optimizer. Your task is to:
1. Analyze the job description to identify:
   - Required technical skills and tools
   - Essential soft skills
   - Key responsibilities
   - Industry-specific keywords
   - Required qualifications and experience

2. Review and optimize the resume content by:
   - Incorporating relevant keywords naturally
   - Highlighting matching experiences and skills
   - Using strong action verbs
   - Adding quantifiable achievements
   - Ensuring ATS-friendly formatting
   - Maintaining professional tone

3. CRITICAL FORMATTING RULES:
   - Keep the EXACT same document structure
   - Preserve all section headings exactly as they appear
   - Maintain all dates and company names
   - Return a valid JSON object where each key matches original sections
   - Ensure proper punctuation and formatting
   - Keep education details unchanged

4. Focus on:
   - Making each bullet point relevant to the job
   - Using terminology from the job description
   - Highlighting transferable skills
   - Maintaining clear, concise language

Your output MUST be a properly formatted JSON object where:
- Each key exactly matches a section from the original resume
- Each value contains the optimized content for that section
- All formatting and structure remain identical to the original"""

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
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
        
        # Extract and validate the response
        optimized_content = response.choices[0].message.content
        print("Received OpenAI response, attempting to parse...")
        print(f"Raw response content: {optimized_content}")
        
        try:
            # Clean the response string if needed
            cleaned_content = optimized_content.strip()
            if cleaned_content.startswith("```json"):
                cleaned_content = cleaned_content[7:]
            if cleaned_content.endswith("```"):
                cleaned_content = cleaned_content[:-3]
            
            parsed_content = json.loads(cleaned_content)
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
        
        # Read and process the document
        content = await file.read()
        doc = Document(BytesIO(content))
        template_doc = DocxTemplate(BytesIO(content))
        
        # Extract content and optimize
        current_content = "\n".join([p.text for p in doc.paragraphs])
        optimized_variables = optimize_resume_content(current_content, job_description)
        
        # Render optimized template
        template_doc.render(optimized_variables)
        
        # Save and return optimized document
        output = BytesIO()
        template_doc.save(output)
        output.seek(0)
        
        # Store files in Supabase
        sanitized_filename = sanitize_filename(file.filename)
        
        try:
            # Store original resume
            supabase.storage.from_("resume_templates").upload(
                f"original_{timestamp}_{sanitized_filename}",
                content
            )
            
            # Store optimized resume
            supabase.storage.from_("resume_templates").upload(
                f"optimized_{timestamp}_{sanitized_filename}",
                output.getvalue()
            )
            
            # Store job description
            supabase.storage.from_("resume_templates").upload(
                f"jd_{timestamp}.txt",
                job_description.encode('utf-8')
            )
        except Exception as e:
            print(f"Storage error: {str(e)}")
            # Continue processing even if storage fails
        
        # Return the optimized document
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename=optimized_{sanitized_filename}",
                "Access-Control-Expose-Headers": "Content-Disposition",
                "Access-Control-Allow-Origin": "*"
            }
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

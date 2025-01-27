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

load_dotenv()

app = FastAPI(title="Resume Optimizer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600,
)

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is not set")

client = OpenAI(api_key=api_key)

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not supabase_url or not supabase_key:
    raise ValueError("Supabase environment variables are not properly set")

supabase = create_client(supabase_url, supabase_key)

def extract_template_variables(doc: Document) -> Dict[str, str]:
    variables = {}
    current_section = None
    section_content = []
    
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
            
        if text.isupper() or text.endswith(':'):
            if current_section and section_content:
                variables[current_section] = '\n'.join(section_content)
                section_content = []
            current_section = text.lower().replace(':', '').strip()
        else:
            if current_section:
                section_content.append(text)
            
    if current_section and section_content:
        variables[current_section] = '\n'.join(section_content)
        
    return variables

def optimize_resume_content(template_vars: Dict[str, str], job_description: str) -> Dict[str, str]:
    try:
        system_prompt = """You are an expert ATS resume optimizer. Optimize the resume content while maintaining the EXACT format:
        1. Return a valid JSON object with the same keys as input
        2. For each section:
           - Preserve exact format (line breaks, bullet points)
           - Add relevant keywords from job description naturally
           - Use industry-standard terminology
           - Include quantifiable achievements
           - Use strong action verbs
           - Keep same number of lines/bullets
           - Maintain all dates and company names
        3. DO NOT change:
           - Section structure
           - Number of lines
           - Formatting
        4. Focus on:
           - Relevant skills and experiences
           - Natural keyword integration
           - Professional tone
        Return only a JSON object."""

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Original Resume:\n{json.dumps(template_vars, indent=2)}\n\nJob Description:\n{job_description}\n\nOptimize while maintaining format. Return only JSON."}
            ],
            temperature=0.7
        )
        
        optimized_content = json.loads(response.choices[0].message.content.strip())
        
        # Verify structure preservation
        for key in template_vars.keys():
            if key not in optimized_content:
                optimized_content[key] = template_vars[key]
            else:
                orig_lines = template_vars[key].split('\n')
                opt_lines = optimized_content[key].split('\n')
                if len(orig_lines) != len(opt_lines):
                    optimized_content[key] = template_vars[key]
                    
        return optimized_content
            
    except Exception as e:
        print(f"Optimization error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to optimize resume: {str(e)}")

def verify_optimization(original_content: Dict[str, str], optimized_content: Dict[str, str], job_description: str) -> Dict[str, Any]:
    try:
        verification_prompt = f"""
        Analyze the original resume and its optimized version for a job description.
        Original Resume: {json.dumps(original_content)}
        Optimized Resume: {json.dumps(optimized_content)}
        Job Description: {job_description}
        
        Evaluate and return a JSON with:
        1. optimization_score (0-100)
        2. feedback (string explaining the changes and their effectiveness)
        3. maintains_format (boolean)
        """

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an expert resume optimization analyzer."},
                {"role": "user", "content": verification_prompt}
            ],
            temperature=0.7
        )
        
        verification_result = json.loads(response.choices[0].message.content)
        return verification_result
    except Exception as e:
        print(f"Verification error: {str(e)}")
        return {
            "optimization_score": 0,
            "feedback": f"Verification failed: {str(e)}",
            "maintains_format": False
        }

@app.post("/process-resume/")
async def process_resume(
    file: UploadFile = File(...),
    job_description: str = Form(...)
):
    try:
        print(f"Processing resume: {file.filename}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        content = await file.read()
        doc = Document(BytesIO(content))
        template_doc = DocxTemplate(BytesIO(content))
        
        template_vars = extract_template_variables(doc)
        optimized_vars = optimize_resume_content(template_vars, job_description)
        
        # Verify optimization
        verification_result = verify_optimization(template_vars, optimized_vars, job_description)
        
        template_doc.render(optimized_vars)
        
        output = BytesIO()
        template_doc.save(output)
        output.seek(0)
        
        # Store in Supabase
        filename = re.sub(r'[^\w\-\.]', '_', file.filename).strip('_').strip()
        
        try:
            # Upload original resume
            original_path = f"original_{timestamp}_{filename}"
            supabase.storage.from_("resume_templates").upload(
                original_path,
                content
            )
            
            # Upload optimized resume
            optimized_path = f"optimized_{timestamp}_{filename}"
            supabase.storage.from_("resume_templates").upload(
                optimized_path,
                output.getvalue()
            )
            
            # Store optimization record
            supabase.table('resume_optimizations').insert({
                'original_resume_path': original_path,
                'optimized_resume_path': optimized_path,
                'job_description': job_description,
                'optimization_score': verification_result.get('optimization_score', 0),
                'verification_feedback': verification_result.get('feedback', ''),
                'status': 'completed'
            }).execute()
            
        except Exception as e:
            print(f"Storage error: {str(e)}")
        
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename=optimized_{filename}",
                "Access-Control-Expose-Headers": "Content-Disposition",
                "Access-Control-Allow-Origin": "*"
            }
        )
        
    except Exception as e:
        print(f"Processing error: {str(e)}")
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

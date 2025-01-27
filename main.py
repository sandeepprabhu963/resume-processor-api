from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from docx import Document
from docxtpl import DocxTemplate
from openai import OpenAI
import json
import os
from io import BytesIO
from typing import Dict, Any
from dotenv import load_dotenv
from datetime import datetime
import re
from supabase import create_client
from pydantic import BaseModel

load_dotenv()

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize OpenAI client
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is not set")
client = OpenAI(api_key=api_key)

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not supabase_url or not supabase_key:
    raise ValueError("Supabase environment variables are not properly set")
supabase = create_client(supabase_url, supabase_key)

class ResumeResponse(BaseModel):
    filename: str
    content_type: str
    content: bytes

def extract_template_variables(doc: Document) -> Dict[str, str]:
    try:
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
    except Exception as e:
        print(f"Error extracting template variables: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to process resume template. Please ensure the document is properly formatted."
        )

def optimize_resume_content(template_vars: Dict[str, str], job_description: str) -> Dict[str, str]:
    try:
        # Convert template_vars to a properly formatted JSON string
        template_vars_json = json.dumps(template_vars, ensure_ascii=False)
        
        system_prompt = """You are an expert ATS resume optimizer. Your task is to optimize the resume content while maintaining the exact format:
        1. Return ONLY a valid JSON object with the same keys as input
        2. For each section:
           - Keep exact format (bullets, spacing)
           - Add relevant keywords from job description
           - Use industry terms
           - Include metrics
           - Use action verbs
           - Keep same number of lines
           - Keep dates and company names
        3. DO NOT change structure or formatting
        4. Focus on relevant skills and natural keyword integration"""

        print("Sending request to OpenAI with template vars:", template_vars_json)
        
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Original Resume:\n{template_vars_json}\n\nJob Description:\n{job_description}"}
            ],
            temperature=0.7
        )
        
        # Get the response content
        response_content = response.choices[0].message.content
        print("Received response from OpenAI:", response_content)
        
        # Parse the response content as JSON
        try:
            optimized_content = json.loads(response_content)
        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {str(e)}")
            print(f"Response content that failed to parse: {response_content}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to parse optimized content: {str(e)}"
            )
        
        # Validate and maintain structure
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
        raise HTTPException(
            status_code=500,
            detail=f"Failed to optimize resume content: {str(e)}"
        )

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
        
        try:
            content = await file.read()
            if len(content) == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Empty file uploaded. Please try again with a valid document."
                )
            
            doc = Document(BytesIO(content))
            template_doc = DocxTemplate(BytesIO(content))
        except Exception as e:
            print(f"Document processing error: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail="Failed to read document. Please ensure it's a valid .docx file."
            )
        
        template_vars = extract_template_variables(doc)
        optimized_vars = optimize_resume_content(template_vars, job_description)
        
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
                'status': 'completed'
            }).execute()
            
        except Exception as e:
            print(f"Storage error: {str(e)}")
            # Continue even if storage fails - we don't want to block the user from getting their resume
        
        output.seek(0)
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

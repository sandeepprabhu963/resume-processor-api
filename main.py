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
        print("Starting template variable extraction...")
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
            
        print("Extracted variables:", json.dumps(variables, indent=2))
        return variables
    except Exception as e:
        print(f"Error in extract_template_variables: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process resume template: {str(e)}"
        )

def optimize_resume_content(template_vars: Dict[str, str], job_description: str) -> Dict[str, str]:
    try:
        print("Starting resume optimization...")
        print("Template variables:", json.dumps(template_vars, indent=2))
        print("Job description:", job_description)
        
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

        try:
            # Validate input data
            if not template_vars or not job_description:
                raise ValueError("Missing required input data")

            print("Making OpenAI API call...")
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Original Resume:\n{json.dumps(template_vars, ensure_ascii=False)}\n\nJob Description:\n{job_description}"}
                ],
                temperature=0.7,
                max_tokens=2000
            )
            
            print("OpenAI API response received")
            
            # Validate API response
            if not response or not response.choices:
                raise ValueError("Invalid response structure from OpenAI API")
            
            if not response.choices[0] or not response.choices[0].message:
                raise ValueError("No message content in OpenAI response")
            
            response_content = response.choices[0].message.content
            if not response_content:
                raise ValueError("Empty response content from OpenAI API")
            
            print("Raw OpenAI response:", response_content)
            
            # Parse and validate JSON response
            try:
                optimized_content = json.loads(response_content)
                if not isinstance(optimized_content, dict):
                    raise ValueError("OpenAI response is not a valid JSON object")
                
                print("Successfully parsed optimized content")
                
                # Validate structure matches original
                for key in template_vars.keys():
                    if key not in optimized_content:
                        print(f"Missing key in optimized content: {key}")
                        optimized_content[key] = template_vars[key]
                    else:
                        orig_lines = template_vars[key].split('\n')
                        opt_lines = optimized_content[key].split('\n')
                        if len(orig_lines) != len(opt_lines):
                            print(f"Line count mismatch for {key}")
                            optimized_content[key] = template_vars[key]
                
                return optimized_content
                
            except json.JSONDecodeError as e:
                print(f"JSON parsing error: {str(e)}")
                print(f"Response content that failed to parse: {response_content}")
                raise ValueError(f"Failed to parse OpenAI response: {str(e)}")
                
        except Exception as api_error:
            print(f"OpenAI API error: {str(api_error)}")
            raise ValueError(f"OpenAI API error: {str(api_error)}")
            
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
                detail=f"Failed to read document: {str(e)}"
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
            # Continue even if storage fails
        
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

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

# Initialize Gemini API
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY environment variable is not set")
genai.configure(api_key=api_key)

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not supabase_url or not supabase_key:
    raise ValueError("Supabase environment variables are not properly set")
supabase = create_client(supabase_url, supabase_key)

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
                
            # Check if this is a section header
            if text.isupper() or text.endswith(':'):
                if current_section and section_content:
                    variables[current_section] = '\n'.join(section_content)
                    section_content = []
                current_section = text.lower().replace(':', '').strip()
            else:
                if current_section:
                    section_content.append(text)
                
        # Add the last section if it exists
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
        
        # Construct a more specific prompt for Gemini
        system_prompt = """You are an expert ATS resume optimizer. Analyze the resume content and job description, then return an optimized version that:
        1. Maintains the exact same structure and format as the input resume
        2. Integrates relevant keywords from the job description naturally
        3. Emphasizes matching skills and experiences
        4. Uses strong action verbs
        5. Includes metrics where possible
        6. Preserves all dates and company names
        
        Return ONLY a valid JSON object with the exact same keys as the input resume, containing the optimized content.
        Do not add or remove any sections."""

        # Validate input data
        if not template_vars or not job_description:
            raise ValueError("Missing required input data")

        try:
            print("Making Gemini API call...")
            model = genai.GenerativeModel('gemini-pro')
            
            # Create a more structured prompt
            prompt = f"""
            {system_prompt}

            Original Resume Content:
            {json.dumps(template_vars, ensure_ascii=False, indent=2)}

            Job Description:
            {job_description}

            Please optimize the resume content while maintaining the exact same JSON structure.
            """
            
            response = model.generate_content(prompt)
            print("Gemini API response received")
            print("Raw response:", response.text)
            
            if not response.text:
                raise ValueError("Empty response from Gemini API")
            
            # Extract JSON from response
            try:
                # Find JSON content within the response
                json_str = response.text
                if '```json' in json_str:
                    json_str = json_str.split('```json')[1].split('```')[0]
                elif '```' in json_str:
                    json_str = json_str.split('```')[1].split('```')[0]
                
                optimized_content = json.loads(json_str.strip())
                if not isinstance(optimized_content, dict):
                    raise ValueError("Response is not a valid JSON object")
                
                # Verify all original keys are present
                missing_keys = set(template_vars.keys()) - set(optimized_content.keys())
                if missing_keys:
                    raise ValueError(f"Missing keys in optimized content: {missing_keys}")
                
                print("Successfully parsed optimized content")
                return optimized_content
                
            except json.JSONDecodeError as e:
                print(f"JSON parsing error: {str(e)}")
                print(f"Failed to parse content: {response.text}")
                raise ValueError(f"Failed to parse Gemini response: {str(e)}")
                
        except Exception as api_error:
            print(f"Gemini API error: {str(api_error)}")
            raise ValueError(f"Gemini API error: {str(api_error)}")
            
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
        
        # Extract and optimize content
        template_vars = extract_template_variables(doc)
        optimized_vars = optimize_resume_content(template_vars, job_description)
        
        # Render optimized content
        template_doc.render(optimized_vars)
        
        output = BytesIO()
        template_doc.save(output)
        output.seek(0)
        
        # Store in Supabase
        filename = re.sub(r'[^\w\-\.]', '_', file.filename).strip('_').strip()
        
        try:
            # Store original and optimized content
            original_path = f"original_{timestamp}_{filename}"
            optimized_path = f"optimized_{timestamp}_{filename}"
            
            # Upload files to Supabase storage
            supabase.storage.from_("resume_templates").upload(
                original_path,
                content
            )
            
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

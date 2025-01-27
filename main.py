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

supabase = create_client(supabase_url, supabase_key)

def extract_template_variables(doc: Document) -> Dict[str, str]:
    """Extract template variables and their content from the document."""
    variables = {}
    current_section = None
    section_content = []

    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue

        # Check if this is a section header (all caps or ends with colon)
        if text.isupper() or text.endswith(':'):
            # Save previous section if exists
            if current_section and section_content:
                variables[current_section] = '\n'.join(section_content)
                section_content = []
            current_section = text.lower().replace(':', '').strip()
        else:
            if current_section:
                # Preserve formatting by keeping original paragraph text
                section_content.append(text)

    # Add the last section if exists
    if current_section and section_content:
        variables[current_section] = '\n'.join(section_content)

    return variables

def optimize_resume_content(template_vars: Dict[str, str], job_description: str) -> Dict[str, str]:
    """Optimize resume content while preserving structure."""
    try:
        system_prompt = """You are an expert ATS resume optimizer. Your task is to optimize the resume content while EXACTLY maintaining the original format and structure. Follow these requirements:
        system_prompt = """You are an expert ATS resume optimizer. Your task is to optimize the resume content while maintaining the EXACT format and structure. Follow these strict requirements:
1. Return ONLY a valid JSON object with the exact same keys as the input
2. For each section:
   - Keep the exact same format, including line breaks and spacing
   - Optimize content to match job requirements by:
     * Including relevant keywords from the job description
     * Using industry-specific terminology
     * Adding quantifiable achievements where possible
     * Using strong action verbs
   - Maintain the same number of bullet points/paragraphs
   - Keep dates, company names, and education details unchanged
   - Keep the exact same format, including line breaks and bullet points
   - Optimize content by:
     * Incorporating relevant keywords from the job description naturally
     * Using industry-standard terminology that matches the job requirements
     * Adding specific, quantifiable achievements where possible
     * Using strong action verbs that demonstrate impact
     * Highlighting skills and experiences that align with the job
   - Maintain the exact same number of lines and bullet points
   - Keep all dates, company names, and education details unchanged
3. DO NOT:
   - Add new sections
   - Remove existing sections
   - Change section titles
   - Alter the document structure
   - Add or remove any sections
   - Change section titles or structure
   - Modify formatting or layout
4. Focus on:
   - Matching skills and experiences to job requirements
   - Highlighting relevant achievements
   - Using keywords from the job description naturally
   - Maintaining readability and flow
   - Making each bullet point more impactful and relevant to the job
   - Using keywords from the job description in a natural, contextual way
   - Highlighting transferable skills that match the job requirements
   - Maintaining professional tone and clarity
The response must be a clean JSON object without any markdown formatting."""
The response must be a clean JSON object without any markdown formatting or additional text."""

        print("Template variables:", json.dumps(template_vars, indent=2))
        print("Job description:", job_description)
        print("Processing resume optimization with:")
        print("Job Description:", job_description)
        print("Original Template Variables:", json.dumps(template_vars, indent=2))

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": f"""Original Resume Sections:
                    "content": f"""Original Resume Content:
{json.dumps(template_vars, indent=2)}
Job Description:
{job_description}
Return only a JSON object with the optimized content for each section while maintaining exact formatting."""
Optimize each section while maintaining exact formatting and structure. Return only a JSON object."""
                }
            ],
            temperature=0.7,
            max_tokens=2500
        )

        # Get the response content
        optimized_content = response.choices[0].message.content
        print(f"Raw OpenAI response: {optimized_content}")

        # Clean and parse the JSON response
        try:
            # Remove any markdown formatting
            cleaned_content = optimized_content.strip()
            if cleaned_content.startswith('```json'):
                cleaned_content = cleaned_content[7:]
            if cleaned_content.endswith('```'):
                cleaned_content = cleaned_content[:-3]
            cleaned_content = cleaned_content.strip()

            # Parse the JSON
            parsed_content = json.loads(cleaned_content)

            # Verify all original sections are present
            # Verify all original sections are present and properly formatted
            for key in template_vars.keys():
                if key not in parsed_content:
                    print(f"Missing section {key} in optimized content, using original")
                    parsed_content[key] = template_vars[key]
                else:
                    # Ensure the optimized content maintains the same basic structure
                    orig_lines = template_vars[key].split('\n')
                    opt_lines = parsed_content[key].split('\n')
                    if len(orig_lines) != len(opt_lines):
                        print(f"Section {key} has different number of lines, using original")
                        parsed_content[key] = template_vars[key]

            return parsed_content

        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {str(e)}")
            print(f"Content causing error: {cleaned_content}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to parse optimization result: {str(e)}\nContent: {cleaned_content}"
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

        # Read the document
        content = await file.read()
        doc = Document(BytesIO(content))
        template_doc = DocxTemplate(BytesIO(content))

        # Extract template variables and their content
        template_vars = extract_template_variables(doc)
        print(f"Extracted template variables: {json.dumps(template_vars, indent=2)}")

        # Optimize content while preserving structure
        optimized_vars = optimize_resume_content(template_vars, job_description)
        print(f"Optimized variables: {json.dumps(optimized_vars, indent=2)}")

        # Render template with optimized content
        template_doc.render(optimized_vars)

        # Save optimized document
        output = BytesIO()
        template_doc.save(output)
        output.seek(0)

        # Store files in Supabase
        sanitized_filename = re.sub(r'[^\w\-\.]', '_', file.filename).strip('_').strip()

        try:
            # Store original and optimized resumes
            supabase.storage.from_("resume_templates").upload(
                f"original_{timestamp}_{sanitized_filename}",
                content
            )
            supabase.storage.from_("resume_templates").upload(
                f"optimized_{timestamp}_{sanitized_filename}",
                output.getvalue()
            )
            supabase.storage.from_("resume_templates").upload(
                f"jd_{timestamp}.txt",
                job_description.encode('utf-8')
            )
        except Exception as e:
            print(f"Storage error: {str(e)}")
            # Continue processing even if storage fails

        # Return optimized document
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

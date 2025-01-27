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

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Initialize API clients and configurations
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY environment variable is not set")
genai.configure(api_key=api_key)

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not supabase_url or not supabase_key:
    raise ValueError("Supabase environment variables are not properly set")
supabase = create_client(supabase_url, supabase_key)

def docx_to_json(doc: Document) -> Dict[str, Any]:
    """Convert DOCX document to JSON format with improved structure handling."""
    try:
        print("Starting DOCX to JSON conversion...")
        json_data = {
            "sections": {},
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "format_version": "1.0"
            }
        }
        
        current_section = None
        section_content = []
        
        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            
            # Enhanced section header detection
            if (text.isupper() or 
                text.endswith(':') or 
                any(header in text.lower() for header in 
                    ['summary', 'experience', 'education', 'skills', 'contact', 'objective'])):
                
                if current_section and section_content:
                    json_data["sections"][current_section] = {
                        "content": section_content,
                        "style": "regular"
                    }
                    section_content = []
                
                current_section = text.lower().replace(':', '').strip()
                
            else:
                if current_section:
                    # Preserve formatting and structure
                    para_data = {
                        "text": text,
                        "style": "bullet" if text.startswith('•') or text.startswith('-') else "regular",
                        "formatting": {
                            "bold": any(run.bold for run in paragraph.runs),
                            "italic": any(run.italic for run in paragraph.runs)
                        }
                    }
                    section_content.append(para_data)
                elif not current_section and text:
                    current_section = "header"
                    section_content.append({
                        "text": text,
                        "style": "regular",
                        "formatting": {"bold": True}
                    })
        
        # Add the last section
        if current_section and section_content:
            json_data["sections"][current_section] = {
                "content": section_content,
                "style": "regular"
            }
        
        print("Successfully converted DOCX to JSON")
        return json_data
        
    except Exception as e:
        print(f"Error in docx_to_json: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to convert resume to JSON: {str(e)}")

def json_to_docx(template_doc: DocxTemplate, json_data: Dict[str, Any]) -> BytesIO:
    """Convert JSON back to DOCX format with improved formatting preservation."""
    try:
        print("Starting JSON to DOCX conversion...")
        
        # Create context for template
        context = {}
        
        for section_name, section_data in json_data.get("sections", {}).items():
            # Convert section name to valid template variable
            template_var = re.sub(r'[^\w]', '_', section_name.lower())
            
            formatted_content = []
            for item in section_data.get("content", []):
                text = item.get("text", "").strip()
                if not text:
                    continue
                
                # Apply formatting
                if item.get("style") == "bullet":
                    if not text.startswith('•'):
                        text = f"• {text}"
                
                # Handle special formatting
                if item.get("formatting", {}).get("bold"):
                    text = f"**{text}**"
                if item.get("formatting", {}).get("italic"):
                    text = f"*{text}*"
                
                formatted_content.append(text)
            
            # Join with proper line breaks
            context[template_var] = '\n'.join(formatted_content)
            
            # Also provide bullet points separately
            bullet_points = [
                item.get("text") for item in section_data.get("content", [])
                if item.get("style") == "bullet"
            ]
            if bullet_points:
                context[f"{template_var}_bullets"] = bullet_points
        
        print("Template context prepared:", context)
        
        # Render template
        template_doc.render(context)
        
        # Save to BytesIO
        output = BytesIO()
        template_doc.save(output)
        output.seek(0)
        
        print("Successfully converted JSON to DOCX")
        return output
        
    except Exception as e:
        print(f"Error in json_to_docx: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to convert to DOCX: {str(e)}")

def optimize_with_gemini(json_data: Dict[str, str], job_description: str) -> Dict[str, str]:
    """Optimize resume content using Gemini AI with enhanced error handling."""
    try:
        print("Starting Gemini optimization...")
        
        # Configure the model with safety settings
        model = genai.GenerativeModel('gemini-pro',
            safety_settings=[
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ])

        system_prompt = """You are an expert ATS resume optimizer. Analyze the resume content and job description, then return an optimized version that:
        1. Maintains the exact same structure and format as the input resume
        2. Integrates relevant keywords from the job description naturally
        3. Emphasizes matching skills and experiences
        4. Uses strong action verbs
        5. Includes metrics where possible
        6. Preserves all dates and company names
        7. Keeps the same sections in the same order
        
        Return ONLY a valid JSON object with the exact same keys as the input resume, containing the optimized content.
        Do not include any explanations or markdown formatting."""

        prompt = f"""
        {system_prompt}

        Original Resume Content:
        {json.dumps(json_data, ensure_ascii=False, indent=2)}

        Job Description:
        {job_description}

        Please optimize the resume content while maintaining the exact same JSON structure.
        """
        
        # Generate content with retry mechanism
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = model.generate_content(prompt)
                if not response.text:
                    raise ValueError("Empty response from Gemini API")
                
                # Extract JSON from response
                json_str = response.text
                if '```json' in json_str:
                    json_str = json_str.split('```json')[1].split('```')[0]
                elif '```' in json_str:
                    json_str = json_str.split('```')[1].split('```')[0]
                
                optimized_content = json.loads(json_str.strip())
                
                # Verify structure matches
                if set(json_data.keys()) != set(optimized_content.keys()):
                    raise ValueError("Optimized content structure doesn't match original")
                    
                print("Successfully optimized content with Gemini")
                return optimized_content
                
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                print(f"Retry {attempt + 1}/{max_retries} after error: {str(e)}")
                continue
                
    except Exception as e:
        print(f"Gemini optimization error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to optimize resume content: {str(e)}")

@app.post("/process-resume/")
async def process_resume(
    file: UploadFile = File(...),
    job_description: str = Form(...)
) -> StreamingResponse:
    try:
        if not file.filename.endswith('.docx'):
            raise HTTPException(status_code=400, detail="Invalid file format. Please upload a .docx file.")

        print(f"Processing resume: {file.filename}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Read and process the document
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Empty file uploaded")
        
        # Create Document objects
        doc = Document(BytesIO(content))
        template_doc = DocxTemplate(BytesIO(content))
        
        # Convert DOCX to JSON
        json_data = docx_to_json(doc)
        
        # Save original JSON to Supabase
        filename = re.sub(r'[^\w\-\.]', '_', file.filename).strip('_').strip()
        original_json_path = f"original_{timestamp}_{filename}.json"
        
        try:
            json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
            json_bytes = json_str.encode('utf-8')
            
            supabase.storage.from_("resume_templates").upload(
                original_json_path,
                json_bytes
            )
            print(f"Original JSON saved to: {original_json_path}")
        except Exception as e:
            print(f"Error saving original JSON: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to save original JSON: {str(e)}")
        
        # Optimize JSON using Gemini
        optimized_json = optimize_with_gemini(json_data, job_description)
        optimized_json_path = f"optimized_{timestamp}_{filename}.json"
        
        try:
            optimized_json_str = json.dumps(optimized_json, ensure_ascii=False, indent=2)
            optimized_json_bytes = optimized_json_str.encode('utf-8')
            
            supabase.storage.from_("resume_templates").upload(
                optimized_json_path,
                optimized_json_bytes
            )
            print(f"Optimized JSON saved to: {optimized_json_path}")
        except Exception as e:
            print(f"Error saving optimized JSON: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to save optimized JSON: {str(e)}")
        
        # Convert optimized JSON back to DOCX
        output = json_to_docx(template_doc, optimized_json)
        
        # Store optimization record
        try:
            supabase.table('resume_optimizations').insert({
                'original_resume_path': original_json_path,
                'optimized_resume_path': optimized_json_path,
                'job_description': job_description,
                'status': 'completed'
            }).execute()
            print("Optimization record stored in database")
        except Exception as e:
            print(f"Error storing optimization record: {str(e)}")
        
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
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docxtpl import DocxTemplate
import google.generativeai as genai
import json
import os
import hashlib
from io import BytesIO
from typing import Dict, Any, List, Optional
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

# Initialize clients
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY environment variable is not set")
genai.configure(api_key=api_key)

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not supabase_url or not supabase_key:
    raise ValueError("Supabase environment variables are not properly set")
supabase = create_client(supabase_url, supabase_key)

class FormattingManager:
    """Handles document formatting preservation"""
    
    @staticmethod
    def extract_formatting(paragraph) -> Dict[str, Any]:
        formatting = {
            "alignment": str(paragraph.alignment),
            "style_name": paragraph.style.name,
            "line_spacing": paragraph.paragraph_format.line_spacing,
            "runs": []
        }
        
        for run in paragraph.runs:
            run_format = {
                "text": run.text,
                "bold": run.bold,
                "italic": run.italic,
                "underline": run.underline,
                "font_name": run.font.name,
                "font_size": run.font.size.pt if run.font.size else None,
            }
            formatting["runs"].append(run_format)
            
        return formatting

    @staticmethod
    def apply_formatting(paragraph, formatting: Dict[str, Any]):
        if formatting.get("alignment"):
            paragraph.alignment = eval(formatting["alignment"])
        
        if formatting.get("line_spacing"):
            paragraph.paragraph_format.line_spacing = formatting["line_spacing"]

class ResumeProcessor:
    def __init__(self):
        self.formatting_manager = FormattingManager()
        
    def docx_to_json(self, doc: Document) -> Dict[str, Any]:
        """Convert DOCX to JSON with formatting preservation"""
        resume_data = {
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "format_version": "2.0"
            },
            "content": {
                "sections": []
            }
        }

        current_section = None
        current_items = []

        for paragraph in doc.paragraphs:
            formatting = self.formatting_manager.extract_formatting(paragraph)
            
            if paragraph.style.name.startswith('Heading') or paragraph.text.isupper():
                if current_section:
                    resume_data["content"]["sections"].append({
                        "title": current_section,
                        "items": current_items
                    })
                current_section = paragraph.text
                current_items = []
            else:
                if paragraph.text.strip():
                    current_items.append({
                        "text": paragraph.text,
                        "formatting": formatting
                    })

        if current_section:
            resume_data["content"]["sections"].append({
                "title": current_section,
                "items": current_items
            })

        return resume_data

    async def optimize_with_gemini(
        self,
        resume_json: Dict[str, Any],
        job_description: str,
    ) -> Dict[str, Any]:
        """Optimize resume using Gemini AI"""
        try:
            prompt = f"""
            Analyze the following job description and optimize the resume content.
            Job Description: {job_description}

            Resume Content: {json.dumps(resume_json['content'])}

            Please provide an optimized version that:
            1. Matches relevant keywords from the job description
            2. Emphasizes matching skills and experiences
            3. Uses strong action verbs
            4. Maintains the original structure and formatting
            5. Preserves all dates and company names
            """

            model = genai.GenerativeModel('gemini-pro')
            response = await model.generate_content(prompt)
            
            if not response.text:
                raise ValueError("Empty response from Gemini API")
            
            optimized_content = json.loads(response.text)
            resume_json['content'] = optimized_content
            resume_json['metadata']['optimized_at'] = datetime.now().isoformat()

            return resume_json
            
        except Exception as e:
            raise Exception(f"Error optimizing resume: {str(e)}")

    def json_to_docx(self, template_doc: DocxTemplate, json_data: Dict[str, Any]) -> BytesIO:
        """Convert JSON back to DOCX with formatting"""
        try:
            context = {}
            
            for section in json_data["content"]["sections"]:
                section_key = section["title"].lower().replace(' ', '_')
                formatted_items = []
                
                for item in section["items"]:
                    if item["text"].strip():
                        formatted_items.append(item["text"])
                
                context[section_key] = '\n'.join(formatted_items)
            
            template_doc.render(context)
            output = BytesIO()
            template_doc.save(output)
            output.seek(0)
            
            return output
            
        except Exception as e:
            raise Exception(f"Error converting to DOCX: {str(e)}")

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
        
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(
                status_code=400,
                detail="Empty file uploaded"
            )
        
        doc = Document(BytesIO(content))
        template_doc = DocxTemplate(BytesIO(content))
        
        processor = ResumeProcessor()
        
        # Convert to JSON with formatting
        resume_json = processor.docx_to_json(doc)
        
        # Store original JSON
        filename = re.sub(r'[^\w\-\.]', '_', file.filename).strip('_').strip()
        original_json_path = f"original_{timestamp}_{filename}.json"
        
        json_str = json.dumps(resume_json, ensure_ascii=False, indent=2)
        json_bytes = json_str.encode('utf-8')
        
        supabase.storage.from_("resume_templates").upload(
            original_json_path,
            json_bytes
        )
        
        # Optimize JSON
        optimized_json = await processor.optimize_with_gemini(resume_json, job_description)
        optimized_json_path = f"optimized_{timestamp}_{filename}.json"
        
        optimized_json_str = json.dumps(optimized_json, ensure_ascii=False, indent=2)
        optimized_json_bytes = optimized_json_str.encode('utf-8')
        
        supabase.storage.from_("resume_templates").upload(
            optimized_json_path,
            optimized_json_bytes
        )
        
        # Convert back to DOCX
        output = processor.json_to_docx(template_doc, optimized_json)
        
        # Store optimization record
        supabase.table('resume_optimizations').insert({
            'original_resume_path': original_json_path,
            'optimized_resume_path': optimized_json_path,
            'job_description': job_description,
            'status': 'completed'
        }).execute()
        
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename=optimized_{filename}",
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )
        
    except Exception as e:
        print(f"Processing error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
Now let's update the frontend service to handle the enhanced processing:

src/services/pythonService.ts
export const processResume = async (resumeFile: File, jobDescription: string): Promise<Blob> => {
  try {
    console.log('Starting enhanced resume optimization process...', {
      fileName: resumeFile.name,
      fileType: resumeFile.type,
      fileSize: resumeFile.size
    });

    const formData = new FormData();
    formData.append('file', resumeFile);
    formData.append('job_description', jobDescription);

    const response = await fetch('https://resume-processor-api-production.up.railway.app/process-resume/', {
      method: 'POST',
      body: formData,
    });

    console.log('API Response:', {
      status: response.status,
      statusText: response.statusText,
      headers: Object.fromEntries(response.headers.entries())
    });

    if (!response.ok) {
      let errorMessage = 'Failed to process resume';
      try {
        const errorData = await response.json();
        console.error('Error response:', errorData);
        if (errorData.detail) {
          errorMessage = errorData.detail;
        }
      } catch (parseError) {
        console.error('Error parsing error response:', parseError);
      }
      throw new Error(errorMessage);
    }

    const processedBlob = await response.blob();
    if (processedBlob.size === 0) {
      throw new Error('Received empty document from server');
    }

    console.log('Resume processed successfully');
    return processedBlob;

  } catch (error) {
    console.error('Resume processing error:', error);
    throw error;
  }
};

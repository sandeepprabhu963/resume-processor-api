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

def docx_to_json(doc: Document) -> Dict[str, Any]:
    """Convert a docx document to a structured JSON format."""
    json_data = {
        "sections": [],
        "styles": {}
    }
    
    current_section = {"title": "", "content": []}
    
    for paragraph in doc.paragraphs:
        # Store style information
        style = paragraph.style.name
        if style not in json_data["styles"]:
            json_data["styles"][style] = {
                "name": style,
                "font": paragraph.style.font.name if paragraph.style.font else None,
                "size": paragraph.style.font.size if paragraph.style.font else None,
                "bold": paragraph.style.font.bold if paragraph.style.font else None,
                "italic": paragraph.style.font.italic if paragraph.style.font else None
            }
        
        # Detect section headers based on style or formatting
        if paragraph.style.name.lower().startswith(('heading', 'title')):
            if current_section["title"]:  # Save previous section
                json_data["sections"].append(current_section)
            current_section = {"title": paragraph.text, "content": [], "style": style}
        else:
            if paragraph.text.strip():
                current_section["content"].append({
                    "text": paragraph.text,
                    "style": style
                })
    
    # Add the last section
    if current_section["title"] or current_section["content"]:
        json_data["sections"].append(current_section)
    
    return json_data

def json_to_docx(json_data: Dict[str, Any], template_doc: Document) -> Document:
    """Convert JSON back to a docx document while preserving formatting."""
    doc = Document()
    
    # Copy styles from template
    for style in template_doc.styles:
        if style.name not in doc.styles:
            try:
                doc.styles.add_style(style.name, style.type)
            except:
                continue
    
    # Recreate document from JSON
    for section in json_data["sections"]:
        if section["title"]:
            title_para = doc.add_paragraph(section["title"])
            title_para.style = section.get("style", "Heading 1")
        
        for content in section["content"]:
            para = doc.add_paragraph(content["text"])
            if content.get("style"):
                try:
                    para.style = content["style"]
                except:
                    continue
    
    return doc

@app.post("/process-resume/")
async def process_resume(
    file: UploadFile = File(...),
    job_description: str = Form(...)
):
    try:
        print(f"Processing resume: {file.filename}")
        print(f"Job description length: {len(job_description)}")
        
        # Read the uploaded document
        content = await file.read()
        doc = Document(BytesIO(content))
        
        # Convert document to JSON
        resume_json = docx_to_json(doc)
        
        # Process with OpenAI
        sections_prompt = json.dumps(resume_json["sections"])
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": """You are a professional resume optimizer. Your task is to:
                    1. Analyze the JSON structure of the resume and the job description
                    2. Enhance each section's content to better match the job requirements
                    3. Maintain the exact same structure and section titles
                    4. Only modify the content within each section
                    5. Return the optimized content in the exact same JSON format
                    6. Preserve all formatting markers and section organization
                    Return only the optimized JSON structure."""
                },
                {
                    "role": "user",
                    "content": f"Resume Sections:\n{sections_prompt}\n\nJob Description:\n{job_description}\n\nOptimize these resume sections while maintaining exact structure and format."
                }
            ],
            temperature=0.3
        )
        
        print("OpenAI response received")
        
        # Parse the optimized content
        optimized_sections = json.loads(response.choices[0].message.content)
        resume_json["sections"] = optimized_sections
        
        # Convert back to docx
        optimized_doc = json_to_docx(resume_json, doc)
        
        # Save to BytesIO
        doc_io = BytesIO()
        optimized_doc.save(doc_io)
        doc_io.seek(0)
        
        print("Document processed successfully")
        
        # Return the document with appropriate headers
        headers = {
            "Content-Disposition": f"attachment; filename=optimized_{file.filename}",
            "Access-Control-Expose-Headers": "Content-Disposition",
            "Access-Control-Allow-Origin": "*"
        }
        
        return StreamingResponse(
            doc_io,
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

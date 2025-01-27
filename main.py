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

# ... keep existing code (FastAPI setup and middleware configuration)

def docx_to_json(doc: Document) -> Dict[str, str]:
    """Convert DOCX document to JSON format."""
    try:
        print("Converting DOCX to JSON...")
        json_data = {}
        current_section = None
        section_content = []
        
        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
                
            # Identify section headers (all caps or ends with colon)
            if text.isupper() or text.endswith(':'):
                if current_section and section_content:
                    json_data[current_section] = '\n'.join(section_content)
                    section_content = []
                current_section = text.lower().replace(':', '').strip()
            else:
                if current_section:
                    section_content.append(text)
                elif not current_section and text:  # Handle content before first section
                    current_section = "header"
                    section_content.append(text)
        
        # Add the last section
        if current_section and section_content:
            json_data[current_section] = '\n'.join(section_content)
            
        print("Successfully converted DOCX to JSON")
        return json_data
    except Exception as e:
        print(f"Error in docx_to_json: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to convert resume to JSON: {str(e)}"
        )

def optimize_with_gemini(json_data: Dict[str, str], job_description: str) -> Dict[str, str]:
    # ... keep existing code (Gemini optimization function)

def json_to_docx(template_doc: DocxTemplate, json_data: Dict[str, str]) -> BytesIO:
    """Convert JSON back to DOCX format."""
    try:
        print("Converting JSON back to DOCX...")
        
        # Create a context dictionary for the template
        context = {}
        
        # Process each section in the JSON data
        for section_name, content in json_data.items():
            # Convert section name to template variable format
            template_var = section_name.lower().replace(' ', '_')
            
            # Split content into lines and process
            lines = content.split('\n')
            formatted_content = []
            
            for line in lines:
                line = line.strip()
                if line:
                    # Handle bullet points
                    if line.startswith('•') or line.startswith('-'):
                        formatted_content.append(f"• {line.lstrip('•').lstrip('-').strip()}")
                    else:
                        formatted_content.append(line)
            
            # Join the lines back together with proper spacing
            context[template_var] = '\n'.join(formatted_content)
        
        print("Template context prepared:", context)
        
        # Render the template with our context
        template_doc.render(context)
        
        # Save to BytesIO
        output = BytesIO()
        template_doc.save(output)
        output.seek(0)
        
        print("Successfully converted JSON to DOCX")
        return output
    except Exception as e:
        print(f"Error in json_to_docx: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to convert to DOCX: {str(e)}"
        )

@app.post("/process-resume/")
async def process_resume(
    file: UploadFile = File(...),
    job_description: str = Form(...)
) -> StreamingResponse:
    # ... keep existing code (main process_resume function)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

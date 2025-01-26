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

# ... keep existing code (environment variables and app initialization)

def sanitize_filename(filename: str) -> str:
    """Sanitize filename to be safe for storage."""
    # Remove square brackets and their contents
    filename = re.sub(r'\[.*?\]', '', filename)
    # Replace any non-alphanumeric characters (except dots and hyphens) with underscores
    filename = re.sub(r'[^\w\-\.]', '_', filename)
    # Remove any leading/trailing spaces or underscores
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
            var_name = text.strip()[var_start+2:var_end].strip()
            variables[var_name] = ""
    return variables

def optimize_resume_content(resume_text: str, job_description: str) -> Dict[str, str]:
    """Use OpenAI to optimize resume content based on job description."""
    try:
        print("Sending request to OpenAI for resume optimization...")
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": """You are a professional resume optimizer. Your task is to:
                    1. Analyze the resume content and job description
                    2. Enhance the resume content while maintaining the exact same structure
                    3. Return a valid JSON object where:
                       - Each key is a section or field from the original resume
                       - Each value is the optimized content for that section
                    4. Ensure the output is properly formatted JSON with quotes around keys and values"""
                },
                {
                    "role": "user",
                    "content": f"Resume:\n{resume_text}\n\nJob Description:\n{job_description}"
                }
            ],
            temperature=0.3
        )
        
        optimized_content = response.choices[0].message.content
        print("Received response from OpenAI, attempting to parse JSON...")
        print(f"Raw response: {optimized_content}")
        
        try:
            # Try to parse the JSON response
            parsed_content = json.loads(optimized_content)
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

# ... keep existing code (process_resume endpoint and other functions)

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

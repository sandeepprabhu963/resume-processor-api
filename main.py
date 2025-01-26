from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from docx import Document
import openai
import os
from io import BytesIO
from typing import Optional

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.post("/process-resume/")
async def process_resume(
    file: UploadFile = File(...),
    job_description: str = Form(...)
):
    try:
        # Read the uploaded document
        content = await file.read()
        doc = Document(BytesIO(content))
        
        # Extract text while preserving structure
        paragraphs = []
        for para in doc.paragraphs:
            if para.text.strip():
                paragraphs.append(para.text)
        
        original_text = "\n".join(paragraphs)
        
        # Process with OpenAI
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """You are a professional resume optimizer. Your task is to:
                    1. Analyze both the resume and job description
                    2. Enhance the resume content to better match the job requirements
                    3. Maintain the exact same structure and sections as the original resume
                    4. Keep all formatting markers and section titles intact
                    5. Only modify the content within each section to better align with the job
                    6. Ensure the output can be directly used to create a new document
                    Return only the optimized content, structured exactly like the input."""
                },
                {
                    "role": "user",
                    "content": f"Original Resume:\n{original_text}\n\nJob Description:\n{job_description}\n\nOptimize this resume for the job while maintaining exact structure and format."
                }
            ],
            temperature=0.3
        )
        
        optimized_content = response.choices[0].message.content
        
        # Create new document with optimized content
        new_doc = Document()
        
        # Split optimized content into paragraphs and preserve formatting
        for paragraph in optimized_content.split('\n'):
            if paragraph.strip():
                new_doc.add_paragraph(paragraph)
        
        # Save to BytesIO
        doc_io = BytesIO()
        new_doc.save(doc_io)
        doc_io.seek(0)
        
        # Return the document
        return StreamingResponse(
            doc_io,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename=optimized_{file.filename}"
            }
        )
        
    except Exception as e:
        print(f"Error processing resume: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

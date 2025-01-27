from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from document_formatter import DocumentFormatter
from resume_processor import ResumeProcessor
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

document_formatter = DocumentFormatter()
resume_processor = ResumeProcessor()

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

        # Read file content
        content = await file.read()

        # Step 1: Format and save document
        format_result = await document_formatter.process_and_save(content, file.filename)
        
        # Step 2-4: Process the formatted resume
        process_result = await resume_processor.process_resume(
            format_result["formatted_file_path"],
            job_description
        )

        # Return the processed document
        return StreamingResponse(
            process_result["optimized_content"],
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f"attachment; filename=optimized_{file.filename}",
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

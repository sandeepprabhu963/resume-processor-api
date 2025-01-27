import json
from docx import Document
from io import BytesIO
from typing import Dict, Any, Optional
import os
from datetime import datetime
import google.generativeai as genai
from supabase import create_client

class ResumeProcessor:
    def __init__(self):
        # Initialize Supabase client
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not self.supabase_url or not self.supabase_key:
            raise ValueError("Supabase environment variables are not properly set")
        self.supabase = create_client(self.supabase_url, self.supabase_key)

        # Initialize Gemini
        gemini_key = os.getenv("GEMINI_API_KEY")
        if not gemini_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        genai.configure(api_key=gemini_key)
        self.model = genai.GenerativeModel('gemini-pro')

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
            if paragraph.style.name.startswith('Heading'):
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
                        "formatting": {
                            "alignment": str(paragraph.alignment),
                            "style_name": paragraph.style.name
                        }
                    })

        if current_section:
            resume_data["content"]["sections"].append({
                "title": current_section,
                "items": current_items
            })

        return resume_data

    async def optimize_with_gemini(self, resume_json: Dict[str, Any], job_description: str) -> Dict[str, Any]:
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

            response = await self.model.generate_content(prompt)
            if not response.text:
                raise ValueError("Empty response from Gemini API")
            
            optimized_content = json.loads(response.text)
            resume_json['content'] = optimized_content
            resume_json['metadata']['optimized_at'] = datetime.now().isoformat()

            return resume_json
            
        except Exception as e:
            raise Exception(f"Error optimizing resume: {str(e)}")

    async def process_resume(self, formatted_file_path: str, job_description: str) -> Dict[str, Any]:
        """Process the formatted resume"""
        try:
            # Get formatted document from Supabase
            formatted_doc_data = self.supabase.storage.from_("resume_templates").download(formatted_file_path)
            doc = Document(BytesIO(formatted_doc_data))

            # Convert to JSON
            resume_json = self.docx_to_json(doc)
            
            # Save JSON to Supabase
            json_filename = f"json_{formatted_file_path}.json"
            self.supabase.storage.from_("resume_templates").upload(
                json_filename,
                json.dumps(resume_json).encode('utf-8')
            )

            # Optimize JSON
            optimized_json = await self.optimize_with_gemini(resume_json, job_description)
            
            # Save optimized JSON
            optimized_filename = f"optimized_{formatted_file_path}.json"
            self.supabase.storage.from_("resume_templates").upload(
                optimized_filename,
                json.dumps(optimized_json).encode('utf-8')
            )

            return {
                "status": "success",
                "json_file_path": json_filename,
                "optimized_file_path": optimized_filename
            }

        except Exception as e:
            print(f"Error in resume processing: {str(e)}")
            raise Exception(f"Failed to process resume: {str(e)}")

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from io import BytesIO
from typing import Dict, Any
import os
from datetime import datetime
from supabase import create_client

class DocumentFormatter:
    def __init__(self):
        # Initialize Supabase client
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not self.supabase_url or not self.supabase_key:
            raise ValueError("Supabase environment variables are not properly set")
        self.supabase = create_client(self.supabase_url, self.supabase_key)

    def format_document(self, doc: Document) -> Document:
        """Apply consistent formatting to the document"""
        # Set document margins
        for section in doc.sections:
            section.top_margin = Inches(0.8)
            section.bottom_margin = Inches(0.8)
            section.left_margin = Inches(0.8)
            section.right_margin = Inches(0.8)

        # Helper function for section headings
        def add_section_heading(text: str):
            heading = doc.add_paragraph()
            heading_run = heading.add_run(text)
            heading_run.bold = True
            heading.style = 'Heading 1'
            heading_format = heading.paragraph_format
            heading_format.space_before = Pt(12)
            heading_format.space_after = Pt(6)
            return heading

        # Clear existing content
        for paragraph in doc.paragraphs[:]:
            p = paragraph._element
            p.getparent().remove(p)

        # Add formatted sections
        # Name and Contact (placeholder - will be replaced with actual data)
        name = doc.add_paragraph()
        name_run = name.add_run('Your Name')
        name_run.bold = True
        name_run.font.size = Pt(14)
        name.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

        contact = doc.add_paragraph()
        contact.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
        contact.add_run('your.email@example.com • Phone Number')

        # Add standard sections
        sections = ['TECHNICAL SKILLS', 'PERSONAL SKILLS', 'EDUCATION', 
                   'PROFESSIONAL SUMMARY', 'WORK EXPERIENCE', 'PROJECTS']
        
        for section_title in sections:
            add_section_heading(section_title)
            # Add placeholder paragraph for content
            p = doc.add_paragraph(style='List Bullet')
            p.add_run('Enter your ' + section_title.lower())

        return doc

    async def process_and_save(self, file_content: bytes, original_filename: str) -> Dict[str, Any]:
        """Process the input file and save to Supabase storage"""
        try:
            # Load and format document
            doc = Document(BytesIO(file_content))
            formatted_doc = self.format_document(doc)

            # Prepare formatted document for storage
            output = BytesIO()
            formatted_doc.save(output)
            output.seek(0)

            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            sanitized_filename = ''.join(c for c in original_filename if c.isalnum() or c in '._- ')
            formatted_filename = f"formatted_{timestamp}_{sanitized_filename}"

            # Save to Supabase storage
            self.supabase.storage.from_("resume_templates").upload(
                formatted_filename,
                output.getvalue()
            )

            return {
                "status": "success",
                "formatted_file_path": formatted_filename,
                "timestamp": timestamp
            }

        except Exception as e:
            print(f"Error in document formatting: {str(e)}")
            raise Exception(f"Failed to format document: {str(e)}")

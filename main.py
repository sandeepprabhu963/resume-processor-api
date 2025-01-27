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
import re
from supabase import create_client
import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords

# Initialize NLTK data
try:
    nltk.data.find('tokenizers/punkt')
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('punkt')
    nltk.download('stopwords')

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize OpenAI client
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is not set")
client = OpenAI(api_key=api_key)

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if not supabase_url or not supabase_key:
    raise ValueError("Supabase environment variables are not properly set")
supabase = create_client(supabase_url, supabase_key)

def analyze_text(text: str) -> Dict[str, Any]:
    """Analyze text using NLTK for keyword extraction."""
    tokens = word_tokenize(text.lower())
    stop_words = set(stopwords.words('english'))
    tokens = [token for token in tokens if token not in stop_words]
    
    skills_pattern = r'\b(?:Python|Java|SQL|AWS|Azure|GCP|Docker|Kubernetes|React|Angular|Vue|Node\.js|JavaScript|TypeScript|C\+\+|Ruby|PHP|HTML|CSS|REST|API|ML|AI|DevOps|CI/CD|Git|Agile|Scrum)\b'
    technical_skills = list(set(re.findall(skills_pattern, text, re.IGNORECASE)))
    
    return {
        'keywords': tokens[:50],  # Limit to top 50 keywords
        'technical_skills': technical_skills
    }

def extract_template_variables(doc: Document) -> Dict[str, str]:
    """Extract content from the document while preserving structure."""
    variables = {}
    current_section = None
    section_content = []
    
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
            
        if text.isupper() or text.endswith(':'):
            if current_section and section_content:
                variables[current_section] = '\n'.join(section_content)
                section_content = []
            current_section = text.lower().replace(':', '').strip()
        else:
            if current_section:
                section_content.append(text)
            
    if current_section and section_content:
        variables[current_section] = '\n'.join(section_content)
        
    return variables

def optimize_resume_content(template_vars: Dict[str, str], job_description: str) -> Dict[str, str]:
    """Optimize resume content while preserving format."""
    try:
        job_analysis = analyze_text(job_description)
        
        system_prompt = """You are an expert ATS resume optimizer. Optimize the resume content while maintaining format:
        1. Return ONLY a valid JSON object with the same keys as input
        2. For each section:
           - Keep exact format (bullets, spacing)
           - Add relevant keywords from job description
           - Use industry terms
           - Include metrics
           - Use action verbs
           - Keep same number of lines
           - Keep dates and company names
        3. DO NOT change structure or formatting
        4. Focus on relevant skills and natural keyword integration"""

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Original Resume:\n{json.dumps(template_vars)}\n\nJob Description:\n{job_description}\n\nKey Skills Required:\n{', '.join(job_analysis['technical_skills'])}"}
            ],
            temperature=0.7
        )
        
        optimized_content = json.loads(response.choices[0].message.content)
        return optimized_content
            
    except Exception as e:
        print(f"Optimization error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to optimize resume: {str(e)}")

@app.post("/process-resume/")
async def process_resume(
    file: UploadFile = File(...),
    job_description: str = Form(...)
):
    try:
        content = await file.read()
        doc = Document(BytesIO(content))
        template_doc = DocxTemplate(BytesIO(content))
        
        template_vars = extract_template_variables(doc)
        optimized_vars = optimize_resume_content(template_vars, job_description)
        
        template_doc.render(optimized_vars)
        
        output = BytesIO()
        template_doc.save(output)
        output.seek(0)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = re.sub(r'[^\w\-\.]', '_', file.filename).strip('_').strip()
        
        try:
            original_path = f"original_{timestamp}_{filename}"
            optimized_path = f"optimized_{timestamp}_{filename}"
            
            supabase.storage.from_("resume_templates").upload(original_path, content)
            supabase.storage.from_("resume_templates").upload(optimized_path, output.getvalue())
            
            supabase.table('resume_optimizations').insert({
                'original_resume_path': original_path,
                'optimized_resume_path': optimized_path,
                'job_description': job_description,
                'status': 'completed'
            }).execute()
            
        except Exception as e:
            print(f"Storage error: {str(e)}")
        
        output.seek(0)
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
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

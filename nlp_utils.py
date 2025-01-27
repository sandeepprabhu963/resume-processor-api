import spacy
import nltk
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.tokenize import sent_tokenize
import re

# Download required NLTK data
nltk.download('punkt')
nltk.download('stopwords')
nltk.download('averaged_perceptron_tagger')

# Load spaCy model
nlp = spacy.load('en_core_web_sm')

def extract_key_phrases(text):
    """Extract important phrases and keywords from text."""
    doc = nlp(text)
    
    # Extract named entities
    entities = [(ent.text, ent.label_) for ent in doc.ents]
    
    # Extract noun phrases
    noun_phrases = [chunk.text for chunk in doc.noun_chunks]
    
    # Extract technical skills and keywords
    skills_pattern = r'\b(?:Python|Java|SQL|AWS|Azure|GCP|Docker|Kubernetes|React|Angular|Vue|Node\.js|JavaScript|TypeScript|C\+\+|Ruby|PHP|HTML|CSS|REST|API|ML|AI|DevOps|CI/CD|Git|Agile|Scrum)\b'
    technical_skills = list(set(re.findall(skills_pattern, text, re.IGNORECASE)))
    
    return {
        'entities': entities,
        'noun_phrases': noun_phrases,
        'technical_skills': technical_skills
    }

def analyze_job_description(job_description):
    """Analyze job description to extract key requirements and skills."""
    # Clean text
    cleaned_text = re.sub(r'\s+', ' ', job_description).strip()
    
    # Extract sentences
    sentences = sent_tokenize(cleaned_text)
    
    # Extract key phrases
    key_phrases = extract_key_phrases(cleaned_text)
    
    # Identify required qualifications
    qualification_keywords = ['required', 'must have', 'qualification', 'requirement']
    qualifications = [sent for sent in sentences if any(keyword in sent.lower() for keyword in qualification_keywords)]
    
    return {
        'key_phrases': key_phrases,
        'required_qualifications': qualifications,
        'sentence_count': len(sentences)
    }

def analyze_resume(resume_text):
    """Analyze resume content to extract key information."""
    # Clean text
    cleaned_text = re.sub(r'\s+', ' ', resume_text).strip()
    
    # Extract key phrases
    key_phrases = extract_key_phrases(cleaned_text)
    
    # Extract experience and skills
    experience_pattern = r'\b(\d+)\s*(?:year|yr)s?\b'
    years_experience = re.findall(experience_pattern, cleaned_text)
    
    return {
        'key_phrases': key_phrases,
        'years_experience': years_experience,
        'text_length': len(cleaned_text)
    }

def calculate_match_score(job_analysis, resume_analysis):
    """Calculate how well the resume matches the job requirements."""
    # Compare technical skills
    job_skills = set(job_analysis['key_phrases']['technical_skills'])
    resume_skills = set(resume_analysis['key_phrases']['technical_skills'])
    skills_match = len(job_skills.intersection(resume_skills)) / len(job_skills) if job_skills else 0
    
    # Compare entities
    job_entities = set(e[0].lower() for e in job_analysis['key_phrases']['entities'])
    resume_entities = set(e[0].lower() for e in resume_analysis['key_phrases']['entities'])
    entity_match = len(job_entities.intersection(resume_entities)) / len(job_entities) if job_entities else 0
    
    return {
        'skills_match_score': round(skills_match * 100, 2),
        'entity_match_score': round(entity_match * 100, 2),
        'overall_match_score': round((skills_match + entity_match) * 50, 2)
    }

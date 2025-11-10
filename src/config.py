"""Configuration management"""
import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

class Config:
    """Configuration settings"""
    
    # Groq AI
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    
    # AWS (optional)
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    
    # Jira (optional)
    JIRA_URL = os.getenv("JIRA_URL")
    JIRA_EMAIL = os.getenv("JIRA_EMAIL")
    JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
    
    # GitHub (optional - NEW)
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    
    # Vercel (optional - NEW)
    VERCEL_TOKEN = os.getenv("VERCEL_TOKEN")
    
    @classmethod
    def validate(cls):
        """Validate required configuration"""
        if not cls.GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY not found in environment variables. "
                "Please create a .env file with:\n"
                "GROQ_API_KEY=gsk_your-key-here\n\n"
                "Get your key from: https://console.groq.com/"
            )
    
    @classmethod
    def is_github_configured(cls):
        """Check if GitHub is configured"""
        return bool(cls.GITHUB_TOKEN)
    
    @classmethod
    def is_vercel_configured(cls):
        """Check if Vercel is configured"""
        return bool(cls.VERCEL_TOKEN)
    
    @classmethod
    def is_aws_configured(cls):
        """Check if AWS is configured"""
        return bool(cls.AWS_ACCESS_KEY_ID and cls.AWS_SECRET_ACCESS_KEY)
    
    @classmethod
    def is_jira_configured(cls):
        """Check if Jira is configured"""
        return bool(cls.JIRA_URL and cls.JIRA_EMAIL and cls.JIRA_API_TOKEN)
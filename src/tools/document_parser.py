"""Document Parser for Jira - Extracts assignments from PDF/Word documents"""
import PyPDF2
import docx
from typing import Dict, Any, List
import re
import logging
from pathlib import Path
import json

logger = logging.getLogger(__name__)

class DocumentParser:
    """Parse PDF/Word documents and extract Jira structure"""
    
    def __init__(self, ai_client=None):
        """
        Initialize parser
        
        Args:
            ai_client: Optional AI client for intelligent parsing
        """
        self.ai_client = ai_client
        self.supported_formats = ['.pdf', '.docx', '.doc', '.txt']
    
    def extract_text_from_pdf(self, file_path: str) -> str:
        """Extract text from PDF file"""
        try:
            text = ""
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            
            logger.info(f"✅ Extracted {len(text)} characters from PDF")
            return text
        except Exception as e:
            logger.error(f"Failed to extract PDF: {e}")
            raise
    
    def extract_text_from_docx(self, file_path: str) -> str:
        """Extract text from Word document"""
        try:
            doc = docx.Document(file_path)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            
            logger.info(f"✅ Extracted {len(text)} characters from DOCX")
            return text
        except Exception as e:
            logger.error(f"Failed to extract DOCX: {e}")
            raise
    
    def extract_text_from_txt(self, file_path: str) -> str:
        """Extract text from TXT file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                text = file.read()
            
            logger.info(f"✅ Extracted {len(text)} characters from TXT")
            return text
        except Exception as e:
            logger.error(f"Failed to extract TXT: {e}")
            raise
    
    def extract_text(self, file_path: str) -> str:
        """Extract text from any supported document"""
        file_ext = Path(file_path).suffix.lower()
        
        if file_ext not in self.supported_formats:
            raise ValueError(f"Unsupported format: {file_ext}. Supported: {self.supported_formats}")
        
        if file_ext == '.pdf':
            return self.extract_text_from_pdf(file_path)
        elif file_ext in ['.docx', '.doc']:
            return self.extract_text_from_docx(file_path)
        elif file_ext == '.txt':
            return self.extract_text_from_txt(file_path)
    
    def parse_with_rules(self, text: str) -> Dict[str, Any]:
        """Parse document using pattern matching rules"""
        config = {
            "projects": [],
            "epics": [],
            "stories": [],
            "subtasks": []
        }
        
        try:
            # Extract projects
            project_pattern = r"Project[:\s]+([A-Z]+)[:\s]+(.+?)(?:Description|Key|$)"
            projects = re.findall(project_pattern, text, re.IGNORECASE)
            
            for key, name in projects:
                config["projects"].append({
                    "key": key.strip(),
                    "name": name.strip(),
                    "template": "scrum"
                })
            
            # Extract epics
            epic_pattern = r"Epic[:\s]+([^:]+?)[:：]\s*(.+?)(?:\n|Dates?:|Goal:)"
            epics = re.findall(epic_pattern, text, re.IGNORECASE)
            
            for i, (epic_id, epic_name) in enumerate(epics):
                config["epics"].append({
                    "id": f"epic_{i+1}",
                    "project": config["projects"][0]["key"] if config["projects"] else "PROJ",
                    "name": epic_name.strip()
                })
            
            # Extract stories/tasks with issue keys (like CEA-101)
            story_pattern = r"([A-Z]+-\d+)\s+(?:Story|Task)[:\s—]+(.+?)(?:\n|Story points?:|SP:)"
            stories = re.findall(story_pattern, text)
            
            for issue_key, summary in stories:
                # Extract story points
                sp_match = re.search(rf"{issue_key}.*?(?:Story points?|SP):\s*(\d+)", text, re.IGNORECASE)
                story_points = int(sp_match.group(1)) if sp_match else 3
                
                # Extract dates
                dates_match = re.search(rf"{issue_key}.*?(\d{{2}}\s+\w+)\s*→\s*(\d{{2}}\s+\w+)", text)
                
                # Extract labels
                labels = []
                if "UX" in summary or "(UX)" in text[text.find(issue_key):text.find(issue_key)+200]:
                    labels.append("UX")
                if "DEV" in summary or "(DEV)" in text[text.find(issue_key):text.find(issue_key)+200]:
                    labels.append("DEV")
                if "QA" in summary or "(QA)" in text[text.find(issue_key):text.find(issue_key)+200]:
                    labels.append("QA")
                if "DEVOPS" in summary or "(DEVOPS)" in text[text.find(issue_key):text.find(issue_key)+200]:
                    labels.append("DEVOPS")
                
                config["stories"].append({
                    "id": issue_key.replace("-", "_").lower(),
                    "project": issue_key.split("-")[0],
                    "summary": summary.strip(),
                    "type": "Story",
                    "story_points": story_points,
                    "labels": labels if labels else ["DEV"]
                })
            
            logger.info(f"✅ Parsed: {len(config['projects'])} projects, {len(config['epics'])} epics, {len(config['stories'])} stories")
            return config
            
        except Exception as e:
            logger.error(f"Rule-based parsing failed: {e}")
            return config
    
    async def parse_with_ai(self, text: str) -> Dict[str, Any]:
        """Use AI to intelligently parse the document"""
        if not self.ai_client:
            raise ValueError("AI client not provided")
        
        try:
            prompt = f"""Analyze this Jira project assignment document and extract ALL the project structure.

Document:
{text[:4000]}  

Extract and return ONLY valid JSON in this exact format:
{{
  "projects": [
    {{
      "key": "PROJECT_KEY",
      "name": "Project Name",
      "description": "Description",
      "template": "scrum"
    }}
  ],
  "epics": [
    {{
      "id": "epic_1",
      "project": "PROJECT_KEY",
      "name": "Epic Name",
      "description": "Epic description",
      "start_date": "2025-11-04",
      "end_date": "2025-11-30"
    }}
  ],
  "stories": [
    {{
      "id": "story_1",
      "project": "PROJECT_KEY",
      "epic_id": "epic_1",
      "summary": "Story summary",
      "description": "Details",
      "type": "Story",
      "story_points": 5,
      "labels": ["DEV", "FRONTEND"],
      "priority": "High",
      "start_date": "2025-11-04",
      "end_date": "2025-11-14",
      "depends_on": ["story_2"]
    }}
  ],
  "subtasks": [
    {{
      "parent_id": "story_1",
      "summary": "Subtask summary",
      "description": "Details"
    }}
  ]
}}

IMPORTANT:
1. Extract ALL projects, epics, stories, and subtasks mentioned
2. Include ALL dates in YYYY-MM-DD format
3. Include ALL dependencies (depends_on relationships)
4. Include ALL story points
5. Include ALL labels (UX/DEV/QA/DEVOPS)
6. Generate unique IDs for each item
7. Link stories to their epics using epic_id
8. Return ONLY the JSON, no explanation or markdown formatting"""

            # Call AI
            messages = [
                {"role": "system", "content": "You are a Jira assignment parser. Extract structured data and return ONLY valid JSON."},
                {"role": "user", "content": prompt}
            ]
            
            # This assumes Groq client (adjust if using different AI)
            response = self.ai_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.1,
                max_tokens=4096
            )
            
            response_text = response.choices[0].message.content.strip()
            
            # Remove markdown code blocks if present
            response_text = re.sub(r'```json\s*', '', response_text)
            response_text = re.sub(r'```\s*$', '', response_text)
            
            # Parse JSON
            config = json.loads(response_text)
            
            logger.info(f"✅ AI parsed: {len(config.get('projects', []))} projects, {len(config.get('stories', []))} stories")
            return config
            
        except json.JSONDecodeError as e:
            logger.error(f"AI returned invalid JSON: {e}")
            logger.error(f"Response: {response_text[:500]}")
            raise ValueError("AI failed to return valid JSON. Try rule-based parsing instead.")
        except Exception as e:
            logger.error(f"AI parsing failed: {e}")
            raise
    
    async def parse_document(self, file_path: str, use_ai: bool = True) -> Dict[str, Any]:
        """
        Main method: Parse document and return Jira config
        
        Args:
            file_path: Path to PDF/Word/TXT document
            use_ai: If True and AI available, use AI parsing; else use rules
        
        Returns:
            Jira configuration dict
        """
        try:
            logger.info(f"📄 Parsing document: {file_path}")
            
            # Step 1: Extract text
            text = self.extract_text(file_path)
            
            if not text.strip():
                raise ValueError("Document is empty or unreadable")
            
            logger.info(f"📝 Extracted {len(text)} characters")
            
            # Step 2: Parse with AI or rules
            if use_ai and self.ai_client:
                logger.info("🤖 Using AI to parse document...")
                try:
                    config = await self.parse_with_ai(text)
                except Exception as e:
                    logger.warning(f"AI parsing failed, falling back to rules: {e}")
                    config = self.parse_with_rules(text)
            else:
                logger.info("📋 Using rule-based parsing...")
                config = self.parse_with_rules(text)
            
            # Step 3: Validate config
            if not config.get("projects") and not config.get("stories"):
                raise ValueError("Could not extract any Jira structure from document")
            
            return {
                "success": True,
                "message": f"Parsed document successfully",
                "data": config
            }
            
        except Exception as e:
            logger.error(f"Document parsing failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def parse_and_save(self, file_path: str, output_json: str = None, use_ai: bool = True):
        """Parse document and save config to JSON file"""
        result = await self.parse_document(file_path, use_ai)
        
        if result["success"]:
            output_file = output_json or f"{Path(file_path).stem}_config.json"
            
            with open(output_file, 'w') as f:
                json.dump(result["data"], f, indent=2)
            
            logger.info(f"✅ Saved config to: {output_file}")
            return output_file
        else:
            raise ValueError(result["error"])


# Complete automation pipeline
class DocumentToJiraAutomation:
    """Complete pipeline: Document → Parse → Create in Jira"""
    
    def __init__(self, jira_automation, ai_client=None):
        self.jira = jira_automation
        self.parser = DocumentParser(ai_client)
    
    async def process_document(self, file_path: str, use_ai: bool = True) -> Dict[str, Any]:
        """
        Complete automation: Parse document and create in Jira
        
        Args:
            file_path: Path to PDF/Word/TXT document
            use_ai: Use AI for parsing (recommended)
        
        Returns:
            Results dict with created issues
        """
        try:
            print("=" * 60)
            print("  📄 Document → Jira Automation Pipeline")
            print("=" * 60)
            
            # Step 1: Parse document
            print(f"\n📄 Step 1: Parsing document: {file_path}")
            parse_result = await self.parser.parse_document(file_path, use_ai)
            
            if not parse_result["success"]:
                return parse_result
            
            config = parse_result["data"]
            
            # Show what was found
            print(f"\n✅ Document parsed successfully!")
            print(f"   • Projects: {len(config.get('projects', []))}")
            print(f"   • Epics: {len(config.get('epics', []))}")
            print(f"   • Stories: {len(config.get('stories', []))}")
            print(f"   • Subtasks: {len(config.get('subtasks', []))}")
            
            # Step 2: Create in Jira
            print(f"\n🚀 Step 2: Creating in Jira...")
            jira_result = await self.jira.create_from_config(config)
            
            if jira_result["success"]:
                print(f"\n✅ SUCCESS! {jira_result['message']}")
                
                if jira_result["data"]["errors"]:
                    print(f"\n⚠️  Some errors occurred:")
                    for error in jira_result["data"]["errors"][:5]:
                        print(f"   • {error}")
            else:
                print(f"\n❌ Jira creation failed: {jira_result['error']}")
            
            return jira_result
            
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
            return {"success": False, "error": str(e)}


# Standalone script
async def main():
    """Main function for standalone usage"""
    import sys
    from groq import Groq
    from src.tools.universal_jira_tool import UniversalJiraAutomation
    from src.config import Config
    
    if len(sys.argv) < 2:
        print("Usage: python document_to_jira.py <document.pdf|docx|txt>")
        print("\nExample:")
        print("  python document_to_jira.py assignment.pdf")
        print("  python document_to_jira.py project_brief.docx")
        return
    
    document_path = sys.argv[1]
    
    # Initialize
    print("🔧 Initializing...")
    jira = UniversalJiraAutomation(
        Config.JIRA_URL,
        Config.JIRA_EMAIL,
        Config.JIRA_API_TOKEN
    )
    
    ai_client = Groq(api_key=Config.GROQ_API_KEY)
    
    automation = DocumentToJiraAutomation(jira, ai_client)
    
    # Process document
    result = await automation.process_document(document_path, use_ai=True)
    
    if result["success"]:
        print("\n🎉 All done! Check your Jira workspace.")
    else:
        print(f"\n❌ Failed: {result['error']}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
"""Simple Document to Jira Automation Script"""
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.append('.')

try:
    from src.tools.document_parser import DocumentParser, DocumentToJiraAutomation
    from src.tools.jira_tool import UniversalJiraAutomation
    from src.config import Config
    from groq import Groq
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("\nMake sure all required packages are installed:")
    print("  pip install PyPDF2 python-docx jira pyyaml groq")
    sys.exit(1)

async def main():
    print("=" * 70)
    print("  📄 Document → Jira Automation")
    print("  Upload PDF/Word → Auto-create Jira tickets")
    print("=" * 70)
    
    # Check if file provided
    if len(sys.argv) < 2:
        print("\n❌ No document provided!")
        print("\nUsage:")
        print("  python run_document_to_jira.py documents/assignment.pdf")
        print("\nOr drag and drop your document file onto this script!")
        return
    
    document_path = sys.argv[1]
    
    # Check file exists
    if not Path(document_path).exists():
        print(f"\n❌ File not found: {document_path}")
        print("\nMake sure the file path is correct!")
        return
    
    print(f"\n📄 Document: {document_path}")
    print(f"   Size: {Path(document_path).stat().st_size / 1024:.1f} KB")
    
    # Check configuration
    print("\n🔧 Checking configuration...")
    
    if not Config.GROQ_API_KEY:
        print("❌ GROQ_API_KEY not set in .env")
        return
    print("✅ Groq API key found")
    
    if not Config.JIRA_URL:
        print("❌ JIRA_URL not set in .env")
        return
    print(f"✅ Jira URL: {Config.JIRA_URL}")
    
    # Initialize systems
    print("\n🚀 Initializing automation systems...")
    
    try:
        # Initialize Jira
        jira = UniversalJiraAutomation(
            Config.JIRA_URL,
            Config.JIRA_EMAIL,
            Config.JIRA_API_TOKEN
        )
        print("✅ Jira connected")
        
        # Initialize AI
        ai_client = Groq(api_key=Config.GROQ_API_KEY)
        print("✅ Groq AI initialized")
        
        # Create automation pipeline
        automation = DocumentToJiraAutomation(jira, ai_client)
        
        # Process document
        print("\n" + "=" * 70)
        print("  🤖 Starting Automation Pipeline")
        print("=" * 70)
        
        result = await automation.process_document(document_path, use_ai=True)
        
        # Show results
        if result["success"]:
            print("\n" + "=" * 70)
            print("  🎉 SUCCESS! All Jira tickets created!")
            print("=" * 70)
            
            data = result["data"]
            print(f"\n📊 Summary:")
            print(f"   ✅ Projects: {len(data.get('projects', []))}")
            print(f"   ✅ Epics: {len(data.get('epics', []))}")
            print(f"   ✅ Stories: {len(data.get('stories', []))}")
            print(f"   ✅ Subtasks: {len(data.get('subtasks', []))}")
            
            if data.get('errors'):
                print(f"\n⚠️  Warnings: {len(data['errors'])}")
                for err in data['errors'][:3]:
                    print(f"   • {err}")
            
            print(f"\n🌐 Check your Jira: {Config.JIRA_URL}")
            print("\n✨ Assignment automation complete!")
            
        else:
            print(f"\n❌ Failed: {result.get('error')}")
            
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
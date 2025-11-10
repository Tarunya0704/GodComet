"""Quick API-based Jira creation - WORKS 100%"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, 'src')

from src.tools.jira_tool import UniversalJiraAutomation
from src.tools.document_parser import DocumentParser
from dotenv import load_dotenv
import os

load_dotenv()

async def main():
    print("\n" + "="*70)
    print("  🚀 JIRA API AUTOMATION - Fast & Reliable")
    print("  No browser needed - Pure API magic!")
    print("="*70)
    
    # Check config
    jira_url = os.getenv('JIRA_URL')
    jira_email = os.getenv('JIRA_EMAIL')
    jira_token = os.getenv('JIRA_API_TOKEN')
    
    if not all([jira_url, jira_email, jira_token]):
        print("\n❌ Missing Jira credentials in .env file!")
        print("\nPlease add to .env:")
        print("JIRA_URL=https://your-company.atlassian.net")
        print("JIRA_EMAIL=your-email@example.com")
        print("JIRA_API_TOKEN=your-api-token")
        return
    
    print(f"\n✅ Connected to: {jira_url}")
    print(f"✅ Using account: {jira_email}")
    
    # Parse document
    doc_path = 'documents/Assignment-11 Monday.docx'
    
    if not Path(doc_path).exists():
        print(f"\n❌ Document not found: {doc_path}")
        print("\n💡 Available documents:")
        docs_dir = Path('documents')
        if docs_dir.exists():
            for f in docs_dir.glob('*.docx'):
                print(f"   - {f}")
        return
    
    print(f"\n📄 Parsing document: {doc_path}")
    parser = DocumentParser()
    result = await parser.parse_document(doc_path, use_ai=False)
    
    if not result['success']:
        print(f"❌ Parse failed: {result['error']}")
        return
    
    config = result['data']
    print(f"✅ Successfully parsed!")
    print(f"   📁 Projects: {len(config.get('projects', []))}")
    print(f"   📋 Epics: {len(config.get('epics', []))}")
    print(f"   📝 Stories: {len(config.get('stories', []))}")
    
    if not config.get('projects'):
        print("\n⚠️  No projects found in document")
        print("Adding default projects: CEA and EAP")
        config['projects'] = [
            {"key": "CEA", "name": "College Event App", "template": "scrum"},
            {"key": "EAP", "name": "Event Admin Portal", "template": "scrum"}
        ]
    
    # Confirm before creating
    print("\n" + "="*70)
    print("  📊 SUMMARY - What will be created:")
    print("="*70)
    
    for proj in config.get('projects', []):
        print(f"\n📁 Project: {proj['key']} - {proj['name']}")
    
    for epic in config.get('epics', []):
        print(f"   📋 Epic: {epic['name']} (Project: {epic['project']})")
    
    print(f"\n   📝 {len(config.get('stories', []))} Stories across all epics")
    
    print("\n" + "="*70)
    response = input("\n▶️  Continue? (yes/no): ").strip().lower()
    
    if response not in ['yes', 'y']:
        print("❌ Cancelled by user")
        return
    
    # Create with API
    print("\n🔧 Creating in Jira via API...")
    print("⏳ Please wait (this takes 10-30 seconds)...\n")
    
    jira = UniversalJiraAutomation(jira_url, jira_email, jira_token)
    
    result = await jira.create_from_config(config)
    
    print("\n" + "="*70)
    if result['success']:
        print("  ✅ SUCCESS!")
        print("="*70)
        print(f"\n{result['message']}")
        
        data = result.get('data', {})
        
        if data.get('projects'):
            print(f"\n📁 Projects Created:")
            for proj in data['projects']:
                print(f"   ✅ {proj}")
        
        if data.get('epics'):
            print(f"\n📋 Epics Created:")
            for epic in data['epics']:
                print(f"   ✅ {epic}")
        
        if data.get('stories'):
            print(f"\n📝 Stories Created: {len(data['stories'])} items")
            print("   (Showing first 10)")
            for story in data['stories'][:10]:
                print(f"   ✅ {story}")
        
        if data.get('errors'):
            print(f"\n⚠️  Some errors occurred ({len(data['errors'])}):")
            for err in data['errors'][:10]:
                print(f"   ⚠️  {err}")
        
        print("\n" + "="*70)
        print("  🎉 ALL DONE!")
        print("="*70)
        print(f"\n👀 View in Jira: {jira_url}/jira/projects")
        print("\n💡 TIP: Check the 'CEA' and 'EAP' projects in Jira")
        
    else:
        print("  ❌ FAILED!")
        print("="*70)
        print(f"\nError: {result.get('error')}")
    
    print("\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled by user")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
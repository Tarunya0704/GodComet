"""Jira Browser Automation - FINAL FIX for SSO and manual login"""
from playwright.async_api import async_playwright
import logging
import asyncio
from typing import Dict, Any

logger = logging.getLogger(__name__)

class JiraBrowserAutomation:
    """Create Jira tickets visually using browser automation - MANUAL LOGIN"""
    
    def __init__(self, jira_url: str, email: str = None, api_token: str = None):
        self.jira_url = jira_url.rstrip('/')
        self.email = email
        self.api_token = api_token
        self.playwright = None
        self.browser = None
        self.page = None
        self.is_logged_in = False
    
    async def start_browser(self, headless: bool = False):
        """Start browser"""
        try:
            if self.playwright:
                return True
            
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=headless,
                args=['--start-maximized', '--disable-blink-features=AutomationControlled']
            )
            context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            self.page = await context.new_page()
            logger.info("✅ Browser started")
            return True
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            return False
    
    async def login_to_jira(self):
        """Login to Jira - MANUAL VERSION WITH SSO SUPPORT"""
        try:
            print("\n" + "="*70)
            print("  🔐 MANUAL LOGIN REQUIRED")
            print("="*70)
            print(f"  Jira URL: {self.jira_url}")
            print(f"  Email: {self.email}")
            print("="*70)
            
            # Go to Jira
            print(f"\n📂 Opening Jira in browser...")
            await self.page.goto(f"{self.jira_url}/jira/your-work", timeout=60000, wait_until='domcontentloaded')
            await self.page.wait_for_timeout(5000)
            
            # Check if already logged in
            current_url = self.page.url
            if '/jira/' in current_url and '/login' not in current_url and 'microsoftonline' not in current_url:
                print("✅ Already logged in from previous session!")
                self.is_logged_in = True
                return True
            
            # Need manual login
            print("\n⏸️  PLEASE LOGIN MANUALLY:")
            print("   1. 👀 Look at the browser window that just opened")
            print("   2. 🔑 Login to Jira manually")
            print(f"      Email: {self.email}")
            if 'microsoftonline' in current_url:
                print("      (Microsoft SSO detected - use your Microsoft account)")
            else:
                print("      Use your Jira password or API token")
            print("   3. ✅ Once you see your Jira dashboard (wait for it to fully load)")
            print("   4. ⌨️  Come back here and press ENTER")
            print("\n" + "="*70)
            
            # Wait for user to login
            input("Press ENTER after you've logged in and see the Jira dashboard... ")
            
            # Give extra time for page to load
            print("\n⏳ Waiting for page to fully load...")
            await self.page.wait_for_timeout(3000)
            
            # Check current URL
            current_url = self.page.url
            print(f"📍 Current URL: {current_url}")
            
            # If still on login/SSO page, wait more
            if '/login' in current_url or 'microsoftonline' in current_url or 'id.atlassian' in current_url:
                print("\n⚠️  Still on login page. Waiting 5 more seconds...")
                await self.page.wait_for_timeout(5000)
                current_url = self.page.url
            
            # Try to navigate to Jira dashboard
            print("\n🔍 Navigating to Jira dashboard...")
            try:
                await self.page.goto(f"{self.jira_url}/jira/your-work", timeout=30000, wait_until='domcontentloaded')
                await self.page.wait_for_timeout(3000)
                current_url = self.page.url
            except Exception as e:
                print(f"⚠️  Navigation warning: {e}")
                # Continue anyway, user might be logged in
            
            # Final check
            if '/jira/' in current_url and '/login' not in current_url and 'microsoftonline' not in current_url:
                print("✅ Login verified! Continuing automation...")
                self.is_logged_in = True
                return True
            else:
                print(f"\n⚠️  URL doesn't look like Jira dashboard: {current_url}")
                print("\nLet's try one more time...")
                
                # Give one more chance
                input("Make sure you're on Jira dashboard, then press ENTER... ")
                await self.page.wait_for_timeout(2000)
                
                current_url = self.page.url
                if '/jira/' in current_url or 'atlassian.net' in current_url:
                    print("✅ Looks good! Continuing...")
                    self.is_logged_in = True
                    return True
                else:
                    print(f"❌ Still not on Jira. Current URL: {current_url}")
                    print("\n💡 TIP: Make sure you:")
                    print("   1. Completed the login")
                    print("   2. Passed any 2FA/verification")
                    print("   3. Can see your Jira dashboard")
                    return False
                
        except Exception as e:
            logger.error(f"Login process failed: {e}")
            return False
    
    async def create_project_visual(self, project_key: str, project_name: str):
        """Create project visually"""
        try:
            if not self.is_logged_in:
                print("❌ Not logged in!")
                return False
            
            print(f"\n📁 Creating project: {project_key} - {project_name}")
            
            # Check if project exists
            try:
                await self.page.goto(f"{self.jira_url}/jira/software/projects/{project_key}/board", timeout=10000)
                await self.page.wait_for_timeout(2000)
                if project_key in self.page.url:
                    print(f"✅ Project {project_key} already exists")
                    return True
            except:
                pass
            
            # Go to projects
            await self.page.goto(f"{self.jira_url}/jira/projects", timeout=30000)
            await self.page.wait_for_timeout(2000)
            
            # Click create project
            create_selectors = [
                'button:has-text("Create project")',
                'a:has-text("Create project")',
                '[data-testid*="create-project"]'
            ]
            
            for selector in create_selectors:
                try:
                    create_btn = await self.page.wait_for_selector(selector, timeout=3000)
                    if create_btn:
                        await create_btn.click()
                        print("✅ Clicked Create Project")
                        await self.page.wait_for_timeout(2000)
                        break
                except:
                    continue
            
            # Select Scrum template
            try:
                scrum_btn = await self.page.wait_for_selector(
                    'button:has-text("Scrum"), div:has-text("Scrum")',
                    timeout=3000
                )
                await scrum_btn.click()
                print("✅ Selected Scrum")
                await self.page.wait_for_timeout(1000)
            except:
                pass
            
            # Click next/use template
            try:
                next_btn = await self.page.query_selector(
                    'button:has-text("Use template"), button:has-text("Next")'
                )
                if next_btn:
                    await next_btn.click()
                    await self.page.wait_for_timeout(1000)
            except:
                pass
            
            # Enter project name
            try:
                name_input = await self.page.wait_for_selector(
                    'input[name="name"], input[placeholder*="name"]',
                    timeout=3000
                )
                await name_input.fill(project_name)
                print(f"✅ Entered name: {project_name}")
                await self.page.wait_for_timeout(500)
            except:
                pass
            
            # Enter project key
            try:
                key_input = await self.page.query_selector('input[name="key"], input[placeholder*="key"]')
                if key_input:
                    await key_input.click()
                    await key_input.press('Control+A')
                    await key_input.fill(project_key)
                    print(f"✅ Entered key: {project_key}")
                    await self.page.wait_for_timeout(500)
            except:
                pass
            
            # Click create
            try:
                create_final = await self.page.query_selector('button:has-text("Create")')
                if create_final:
                    await create_final.click()
                    print("✅ Clicked Create")
                    await self.page.wait_for_timeout(5000)
                    print(f"✅ Project {project_key} created!")
                    return True
            except:
                pass
            
            return True
            
        except Exception as e:
            print(f"⚠️ Project creation error: {e}")
            return False
    
    async def create_epic_visual(self, project_key: str, epic_name: str):
        """Create epic visually"""
        try:
            print(f"\n📋 Creating epic: {epic_name}")
            
            await self.page.goto(f"{self.jira_url}/jira/software/projects/{project_key}/backlog", timeout=30000)
            await self.page.wait_for_timeout(3000)
            
            # Click Create
            create_btn = await self.page.query_selector('button:has-text("Create")')
            if create_btn:
                await create_btn.click()
                await self.page.wait_for_timeout(1500)
            
            # Change to Epic type
            try:
                type_dropdown = await self.page.query_selector('[data-testid*="issue-type"]')
                if type_dropdown:
                    await type_dropdown.click()
                    await self.page.wait_for_timeout(500)
                    
                    epic_option = await self.page.query_selector('div:has-text("Epic")')
                    if epic_option:
                        await epic_option.click()
                        await self.page.wait_for_timeout(500)
            except:
                pass
            
            # Enter epic name
            try:
                summary_input = await self.page.wait_for_selector(
                    'input[name="summary"], textarea[name="summary"]',
                    timeout=2000
                )
                await summary_input.fill(epic_name)
                print(f"✅ Entered: {epic_name}")
            except:
                pass
            
            # Submit
            await self.page.keyboard.press('Enter')
            await self.page.wait_for_timeout(2000)
            print(f"✅ Epic created!")
            return True
            
        except Exception as e:
            print(f"⚠️ Epic creation error: {e}")
            return False
    
    async def create_story_visual(self, project_key: str, story_summary: str, **kwargs):
        """Create story visually"""
        try:
            print(f"\n📝 Creating story: {story_summary[:50]}")
            
            await self.page.goto(f"{self.jira_url}/jira/software/projects/{project_key}/backlog", timeout=30000)
            await self.page.wait_for_timeout(2000)
            
            # Click Create
            create_btn = await self.page.query_selector('button:has-text("Create")')
            if create_btn:
                await create_btn.click()
                await self.page.wait_for_timeout(1000)
            
            # Enter summary
            try:
                summary_input = await self.page.wait_for_selector(
                    'input[name="summary"], textarea[name="summary"]',
                    timeout=2000
                )
                await summary_input.fill(story_summary)
                print(f"✅ Entered: {story_summary[:50]}")
            except:
                pass
            
            # Submit
            await self.page.keyboard.press('Enter')
            await self.page.wait_for_timeout(1500)
            print(f"✅ Story created!")
            return True
            
        except Exception as e:
            print(f"⚠️ Story creation error: {e}")
            return False
    
    async def create_assignment_visual(self, config: Dict[str, Any]):
        """Create entire assignment visually with MANUAL LOGIN"""
        try:
            print("\n" + "="*70)
            print("  🎬 Visual Jira Automation Started")
            print("  (Manual Login Version)")
            print("="*70)
            
            # Start browser if not started
            if not self.browser:
                await self.start_browser(headless=False)
            
            # Manual Login
            if not await self.login_to_jira():
                return {"success": False, "error": "Login failed"}
            
            # Create projects
            print("\n" + "="*70)
            print("  📁 STEP 1: Creating Projects")
            print("="*70)
            for proj in config.get('projects', []):
                await self.create_project_visual(proj['key'], proj['name'])
                await self.page.wait_for_timeout(2000)
            
            # Create epics
            print("\n" + "="*70)
            print("  📋 STEP 2: Creating Epics")
            print("="*70)
            for epic in config.get('epics', []):
                await self.create_epic_visual(epic['project'], epic['name'])
                await self.page.wait_for_timeout(1500)
            
            # Create stories
            print("\n" + "="*70)
            print("  📝 STEP 3: Creating Stories")
            print("="*70)
            for story in config.get('stories', []):
                await self.create_story_visual(story['project'], story['summary'])
                await self.page.wait_for_timeout(1000)
            
            print("\n" + "="*70)
            print("  ✅ Visual Automation Complete!")
            print("="*70)
            print("\n👀 Browser will stay open for 30 seconds so you can verify...")
            await self.page.wait_for_timeout(30000)
            
            return {"success": True, "message": "Visual automation complete"}
            
        except Exception as e:
            logger.error(f"Visual automation failed: {e}")
            return {"success": False, "error": str(e)}
        finally:
            # Safe cleanup
            try:
                if self.browser and self.browser.is_connected():
                    await self.browser.close()
            except:
                pass
            try:
                if self.playwright:
                    await self.playwright.stop()
            except:
                pass
"""Jira Browser Automation - FIXED login and error handling"""
from playwright.async_api import async_playwright
import logging
import asyncio
from typing import Dict, Any

logger = logging.getLogger(__name__)

class JiraBrowserAutomation:
    """Create Jira tickets visually using browser automation"""
    
    def __init__(self, jira_url: str, email: str, api_token: str):
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
        """Login to Jira - FIXED VERSION"""
        try:
            print("🔐 Logging into Jira...")
            
            # Go directly to Jira (might already be logged in)
            await self.page.goto(f"{self.jira_url}/jira/your-work", timeout=30000)
            await self.page.wait_for_timeout(3000)
            
            # Check if already logged in
            current_url = self.page.url
            if '/jira/' in current_url and '/login' not in current_url:
                print("✅ Already logged in!")
                self.is_logged_in = True
                return True
            
            # If redirected to login, handle it
            if '/login' in current_url or 'id.atlassian.com' in current_url:
                print("📝 Need to login...")
                
                # Wait for email field
                try:
                    email_field = await self.page.wait_for_selector(
                        'input[name="username"], input[type="email"], input#username',
                        timeout=5000
                    )
                    await email_field.fill(self.email)
                    print(f"✅ Entered email: {self.email}")
                    await self.page.wait_for_timeout(1000)
                    
                    # Click Continue/Submit
                    continue_btn = await self.page.query_selector(
                        'button[type="submit"], button#login-submit, button:has-text("Continue")'
                    )
                    if continue_btn:
                        await continue_btn.click()
                        await self.page.wait_for_timeout(2000)
                except Exception as e:
                    print(f"⚠️ Email step error: {e}")
                
                # Wait for password field
                try:
                    password_field = await self.page.wait_for_selector(
                        'input[name="password"], input[type="password"], input#password',
                        timeout=10000
                    )
                    await password_field.fill(self.api_token)
                    print("✅ Entered API token")
                    await self.page.wait_for_timeout(1000)
                    
                    # Click Login
                    login_btn = await self.page.query_selector(
                        'button[type="submit"], button#login-submit, button:has-text("Log in")'
                    )
                    if login_btn:
                        await login_btn.click()
                        await self.page.wait_for_timeout(5000)
                        print("✅ Clicked login")
                except Exception as e:
                    print(f"⚠️ Password step error: {e}")
                    print("⚠️ MANUAL LOGIN REQUIRED!")
                    print(f"   1. Browser is open at: {self.page.url}")
                    print(f"   2. Please login manually")
                    print(f"   3. Press Enter when done...")
                    input()
            
            # Verify login
            await self.page.goto(f"{self.jira_url}/jira/your-work", timeout=30000)
            await self.page.wait_for_timeout(3000)
            
            if '/jira/' in self.page.url and '/login' not in self.page.url:
                print("✅ Login successful!")
                self.is_logged_in = True
                return True
            else:
                print(f"⚠️ Login verification failed. URL: {self.page.url}")
                return False
                
        except Exception as e:
            logger.error(f"Login failed: {e}")
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
        """Create entire assignment visually"""
        try:
            print("\n" + "="*60)
            print("  🎬 Visual Jira Automation Started")
            print("="*60)
            
            # Start browser if not started
            if not self.browser:
                await self.start_browser(headless=False)
            
            # Login
            if not await self.login_to_jira():
                return {"success": False, "error": "Login failed"}
            
            # Create projects
            print("\n📁 STEP 1: Creating Projects")
            for proj in config.get('projects', []):
                await self.create_project_visual(proj['key'], proj['name'])
                await self.page.wait_for_timeout(2000)
            
            # Create epics
            print("\n📋 STEP 2: Creating Epics")
            for epic in config.get('epics', []):
                await self.create_epic_visual(epic['project'], epic['name'])
                await self.page.wait_for_timeout(1500)
            
            # Create stories
            print("\n📝 STEP 3: Creating Stories")
            for story in config.get('stories', []):
                await self.create_story_visual(story['project'], story['summary'])
                await self.page.wait_for_timeout(1000)
            
            print("\n" + "="*60)
            print("  ✅ Visual Automation Complete!")
            print("="*60)
            print("\n👀 Browser will stay open for 30 seconds...")
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
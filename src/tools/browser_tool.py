"""Browser automation tool using Playwright"""
from playwright.async_api import async_playwright
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

class BrowserTool:
    """Browser automation using Playwright"""
    
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.page = None
    
    async def start(self, headless: bool = False):
        """Start browser"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=headless)
        self.page = await (await self.browser.new_context()).new_page()
        logger.info("Browser started")
    
    async def navigate(self, url: str) -> Dict[str, Any]:
        """Navigate to URL"""
        try:
            if not self.page:
                await self.start()
            
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            await self.page.goto(url, timeout=30000)
            title = await self.page.title()
            
            return {"success": True, "message": f"Navigated to {url}", "title": title}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def play_youtube(self, query: str) -> Dict[str, Any]:
        """Play YouTube video"""
        try:
            if not self.page:
                await self.start()
            
            await self.page.goto('https://www.youtube.com')
            await self.page.wait_for_timeout(2000)
            
            search = await self.page.wait_for_selector('input#search')
            await search.fill(query)
            await search.press('Enter')
            await self.page.wait_for_timeout(3000)
            
            video = await self.page.wait_for_selector('a#video-title')
            title = await video.get_attribute('title')
            await video.click()
            
            return {"success": True, "message": f"Playing: {title}", "title": title}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def screenshot(self, filename: str = "screenshot.png") -> Dict[str, Any]:
        """Take screenshot"""
        try:
            if not self.page:
                return {"success": False, "error": "Browser not started"}
            
            await self.page.screenshot(path=filename, full_page=True)
            return {"success": True, "message": f"Screenshot saved: {filename}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def close(self):
        """Close browser"""
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
"""Browser automation tool using Playwright - FIXED VERSION"""
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
        try:
            if not self.playwright:
                self.playwright = await async_playwright().start()
                self.browser = await self.playwright.chromium.launch(
                    headless=headless,
                    args=['--start-maximized']
                )
                context = await self.browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                self.page = await context.new_page()
                logger.info("Browser started successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            return False
    
    async def navigate(self, url: str) -> Dict[str, Any]:
        """Navigate to URL"""
        try:
            if not self.page:
                await self.start()
            
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            await self.page.goto(url, timeout=30000, wait_until='domcontentloaded')
            await self.page.wait_for_timeout(2000)
            title = await self.page.title()
            
            logger.info(f"Successfully navigated to {url}")
            return {
                "success": True, 
                "message": f"Navigated to {url}", 
                "data": {"title": title, "url": url}
            }
        except Exception as e:
            logger.error(f"Navigation failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def play_youtube(self, query: str) -> Dict[str, Any]:
        """Play YouTube video - FIXED VERSION"""
        try:
            if not self.page:
                await self.start()
            
            logger.info(f"Searching YouTube for: {query}")
            
            # Method 1: Direct search URL (most reliable)
            search_url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            await self.page.goto(search_url, timeout=30000, wait_until='domcontentloaded')
            
            logger.info("Waiting for search results...")
            await self.page.wait_for_timeout(3000)
            
            # Wait for video results to load
            try:
                # Try multiple selectors (YouTube changes them often)
                video_selectors = [
                    'a#video-title',
                    'ytd-video-renderer a#video-title',
                    'a.yt-simple-endpoint.style-scope.ytd-video-renderer',
                    '#video-title'
                ]
                
                video_element = None
                video_title = None
                
                for selector in video_selectors:
                    try:
                        video_element = await self.page.wait_for_selector(
                            selector, 
                            timeout=5000,
                            state='visible'
                        )
                        if video_element:
                            video_title = await video_element.get_attribute('title')
                            if not video_title:
                                video_title = await video_element.inner_text()
                            logger.info(f"Found video with selector {selector}: {video_title}")
                            break
                    except Exception as e:
                        logger.debug(f"Selector {selector} not found: {e}")
                        continue
                
                if not video_element:
                    # Fallback: Just click any video link
                    logger.warning("Using fallback method to find video")
                    video_element = await self.page.query_selector('a[href*="/watch?v="]')
                    if video_element:
                        video_title = await video_element.get_attribute('title') or query
                
                if video_element:
                    logger.info(f"Clicking video: {video_title}")
                    await video_element.click()
                    await self.page.wait_for_timeout(3000)
                    
                    current_url = self.page.url
                    logger.info(f"Video playing at: {current_url}")
                    
                    return {
                        "success": True,
                        "message": f"Playing video: {video_title}",
                        "data": {
                            "title": video_title,
                            "url": current_url,
                            "query": query
                        }
                    }
                else:
                    return {
                        "success": False,
                        "error": "Could not find any video in search results"
                    }
                    
            except Exception as e:
                logger.error(f"Failed to find/click video: {e}")
                return {
                    "success": False,
                    "error": f"Could not play video: {str(e)}"
                }
                
        except Exception as e:
            logger.error(f"YouTube automation failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def screenshot(self, filename: str = "screenshot.png") -> Dict[str, Any]:
        """Take screenshot"""
        try:
            if not self.page:
                return {"success": False, "error": "Browser not started"}
            
            await self.page.screenshot(path=filename, full_page=True)
            logger.info(f"Screenshot saved: {filename}")
            return {
                "success": True, 
                "message": f"Screenshot saved: {filename}",
                "data": {"filename": filename}
            }
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def close(self):
        """Close browser"""
        try:
            if self.page:
                await self.page.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("Browser closed")
        except Exception as e:
            logger.error(f"Error closing browser: {e}")
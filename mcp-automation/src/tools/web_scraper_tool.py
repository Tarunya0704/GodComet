"""Web Scraper Tool - Extract content from websites"""
import logging
from playwright.async_api import async_playwright
import pandas as pd
from bs4 import BeautifulSoup
import re

logger = logging.getLogger(__name__)

class WebScraperTool:
    """Tool for web scraping and content extraction"""
    
    def __init__(self, ai_client=None):
        self.ai_client = ai_client
        self.playwright = None
        self.browser = None
        self.page = None
        logger.info("Web Scraper Tool initialized")
    
    async def start_browser(self, headless=True):
        """Start browser"""
        if not self.playwright:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=headless)
            self.page = await self.browser.new_page()
    
    async def summarize_article(self, url: str = None) -> dict:
        """Extract and summarize article from current page or URL"""
        try:
            await self.start_browser()
            
            if url:
                await self.page.goto(url, wait_until='domcontentloaded', timeout=30000)
            
            # Extract article content
            content = await self.page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(['script', 'style', 'nav', 'footer', 'header']):
                script.decompose()
            
            # Get text
            text = soup.get_text()
            
            # Clean up text
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)
            
            # Limit to reasonable length
            text = text[:4000]
            
            # Get title
            title_elem = soup.find('title')
            title = title_elem.string if title_elem else "Unknown"
            
            # Use AI to summarize if available
            if self.ai_client:
                summary_prompt = f"""Summarize this article in 3-5 bullet points.

Title: {title}

Content:
{text}

Provide key takeaways."""

                ai_result = await self.ai_client.chat(summary_prompt)
                
                if ai_result.get('success'):
                    return {
                        "success": True,
                        "completed": True,
                        "message": "Article summarized",
                        "data": {
                            "url": self.page.url if self.page else url,
                            "title": title,
                            "summary": ai_result['reply']
                        }
                    }
            
            # Fallback: Return first few paragraphs
            paragraphs = text.split('\n\n')[:3]
            summary = '\n\n'.join(paragraphs)
            
            return {
                "success": True,
                "completed": True,
                "message": "Article content extracted",
                "data": {
                    "url": self.page.url if self.page else url,
                    "title": title,
                    "summary": summary
                }
            }
            
        except Exception as e:
            logger.error(f"Article summarization failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def scrape_table_to_csv(self, selector: str = None, filename: str = "scraped_table.csv") -> dict:
        """Scrape table from current page to CSV"""
        try:
            if not self.page:
                return {"success": False, "error": "Browser not started"}
            
            # Get page content
            content = await self.page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            # Find table
            if selector:
                table = soup.select_one(selector)
            else:
                table = soup.find('table')
            
            if not table:
                return {"success": False, "error": "No table found on page"}
            
            # Extract table data
            rows = []
            for tr in table.find_all('tr'):
                cells = tr.find_all(['td', 'th'])
                row = [cell.get_text(strip=True) for cell in cells]
                if row:
                    rows.append(row)
            
            if not rows:
                return {"success": False, "error": "Table has no data"}
            
            # Create DataFrame
            df = pd.DataFrame(rows[1:], columns=rows[0] if rows else None)
            
            # Save to CSV
            df.to_csv(filename, index=False)
            
            return {
                "success": True,
                "completed": True,
                "message": f"Table scraped to {filename}",
                "data": {
                    "file": filename,
                    "rows": len(df),
                    "columns": len(df.columns),
                    "preview": df.head().to_dict()
                }
            }
            
        except Exception as e:
            logger.error(f"Table scraping failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def research_competitors(self, topic: str, num_results: int = 5) -> dict:
        """Research competitors by searching and analyzing results"""
        try:
            await self.start_browser()
            
            # Search on Google
            search_url = f"https://www.google.com/search?q={topic.replace(' ', '+')}"
            await self.page.goto(search_url, wait_until='domcontentloaded')
            
            # Extract search results
            content = await self.page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            results = []
            search_results = soup.select('div.g')[:num_results]
            
            for result in search_results:
                title_elem = result.select_one('h3')
                link_elem = result.select_one('a')
                snippet_elem = result.select_one('.VwiC3b')
                
                if title_elem and link_elem:
                    results.append({
                        'title': title_elem.get_text(),
                        'url': link_elem.get('href', ''),
                        'snippet': snippet_elem.get_text() if snippet_elem else ''
                    })
            
            # Use AI to analyze if available
            if self.ai_client and results:
                analysis_prompt = f"""Analyze these competitor websites for: {topic}

Results:
{chr(10).join([f"{i+1}. {r['title']}: {r['snippet']}" for i, r in enumerate(results)])}

Provide:
1. Key competitors
2. Common features
3. Unique selling points
4. Recommendations"""

                ai_result = await self.ai_client.chat(analysis_prompt)
                
                if ai_result.get('success'):
                    return {
                        "success": True,
                        "completed": True,
                        "message": f"Found {len(results)} competitors",
                        "data": {
                            "query": topic,
                            "results": results,
                            "analysis": ai_result['reply']
                        }
                    }
            
            return {
                "success": True,
                "completed": True,
                "message": f"Found {len(results)} competitors",
                "data": {
                    "query": topic,
                    "results": results
                }
            }
            
        except Exception as e:
            logger.error(f"Competitor research failed: {e}")
            return {"success": False, "error": str(e)}
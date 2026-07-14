import os
import re
import httpx
import trafilatura
from ant_agent.tools import BaseTool, register_tool

@register_tool
class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Searches the web for queries. Param: search query."

    def execute(self, parameter: str) -> str:
        query = parameter.strip()
        
        # Check Tavily API key from config or environment
        tavily_key = None
        if self.context and hasattr(self.context, "config"):
            tavily_key = self.context.config.get("tavily_api_key")
        if not tavily_key:
            tavily_key = os.environ.get("TAVILY_API_KEY")
            
        if tavily_key:
            try:
                headers = {"Content-Type": "application/json"}
                response = httpx.post(
                    "https://api.tavily.com/search",
                    json={"api_key": tavily_key, "query": query},
                    headers=headers,
                    timeout=10.0
                )
                if response.status_code == 200:
                    results = response.json().get("results", [])
                    out = []
                    for r in results[:5]:
                        out.append(f"Title: {r.get('title')}\nURL: {r.get('url')}\nContent: {r.get('content')}\n")
                    return "\n".join(out)
            except Exception as e:
                return f"Tavily search failed: {e}"

        # Zero-config Fallback: DuckDuckGo HTML Search
        try:
            from urllib.parse import quote
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            # DuckDuckGo HTML search URL
            url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
            response = httpx.get(url, headers=headers, timeout=10.0)
            if response.status_code == 200:
                html = response.text
                # Simple extraction of titles, links, snippets
                # Results are in divs with class result__body
                bodies = re.findall(r'<div class="result__body">.*?</div>\s*</div>', html, re.DOTALL)
                out = []
                for body in bodies[:5]:
                    # Extract title
                    title_match = re.search(r'<a class="result__url"[^>]*>(.*?)</a>', body, re.DOTALL)
                    link_match = re.search(r'href="([^"]+)"', body)
                    snippet_match = re.search(r'<a class="result__snippet"[^>]*>(.*?)</a>', body, re.DOTALL)
                    
                    title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else "No Title"
                    link = link_match.group(1) if link_match else "No URL"
                    snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip() if snippet_match else "No Snippet"
                    
                    # Clean up url parameter if it goes through DDG redirection
                    if "uddg=" in link:
                        link = link.split("uddg=")[1].split("&")[0]
                        # url decode
                        from urllib.parse import unquote
                        link = unquote(link)
                        
                    out.append(f"Title: {title}\nURL: {link}\nSnippet: {snippet}\n")
                
                if out:
                    return "\n".join(out)
                return "No search results returned from DuckDuckGo fallback."
        except Exception as e:
            return f"DuckDuckGo fallback search failed: {e}"

        return "No search providers available. Please set TAVILY_API_KEY env variable."

@register_tool
class WebFetchAndExtractTool(BaseTool):
    name = "web_fetch_and_extract"
    description = "Fetches a URL and returns content as clean text. Param: URL."

    def execute(self, parameter: str) -> str:
        url = parameter.strip()
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = httpx.get(url, headers=headers, follow_redirects=True, timeout=15.0)
            if response.status_code != 200:
                return f"Error: Status code {response.status_code}"
            
            # Use trafilatura for clean extraction
            text = trafilatura.extract(response.text)
            if not text:
                # Fallback to regex parsing if trafilatura returns None
                text = response.text
                text = re.sub(r'<script.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r'<style.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r'<p[^>]*>', '\n\n', text, flags=re.IGNORECASE)
                text = re.sub(r'<br[^>]*>', '\n', text, flags=re.IGNORECASE)
                text = re.sub(r'<h[1-6][^>]*>', '\n\n# ', text, flags=re.IGNORECASE)
                text = re.sub(r'</h[1-6]>', '\n', text, flags=re.IGNORECASE)
                text = re.sub(r'<li[^>]*>', '\n- ', text, flags=re.IGNORECASE)
                text = re.sub(r'<[^>]+>', '', text)
                import html
                text = html.unescape(text)
                text = re.sub(r'\n{3,}', '\n\n', text)
            
            # Truncate output to ~6000 chars to avoid model context overload
            if len(text) > 6000:
                text = text[:6000] + "\n\n... (Truncated due to length)"
                
            return text
        except Exception as e:
            return f"Error fetching URL: {e}"

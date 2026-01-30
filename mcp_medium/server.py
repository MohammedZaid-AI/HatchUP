from mcp.server import FastMCP
import requests
import sys
from bs4 import BeautifulSoup

mcp = FastMCP("Medium MCP")

@mcp.tool()
def search_medium(query: str, num_results: int = 5):
    """
    Search Medium for articles related to a query.
    """
    print(f"[Medium MCP] Searching Medium for: {query}", file=sys.stderr)
    url = f"https://medium.com/search?q={query.replace(' ', '%20')}"
    headers = {"User-Agent": "Mozilla/5.0"}

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return {"error": f"Failed to fetch Medium results. {response.status_code}"}

    soup = BeautifulSoup(response.text, "html.parser")
    articles = []

    for link in soup.select("div.postArticle-readMore a")[:num_results]:
        title = link.get("aria-label") or "Untitled"
        href = link.get("href")
        if href and "?source" in href:
            href = href.split("?source")[0]
        articles.append({"title": title, "link": href})

    return articles

if __name__ == "__main__":
    print("Running Medium MCP...", file=sys.stderr)
    mcp.run(transport="stdio")

from google.auth import transport
from mcp.server import FastMCP
import os
import requests
from dotenv import load_dotenv
from pathlib import Path
import sys


# Load .env from the same directory as this script
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

mcp = FastMCP("Google Search MCP")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")  # your custom search engine ID

@mcp.tool()
def google_search(query: str, num_results: int = 5):
    """Search Google using the Custom Search API."""
    url = f"https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_API_KEY,
        "cx": SEARCH_ENGINE_ID,
        "q": query,
        "num": num_results
    }

    response = requests.get(url, params=params)
    if response.status_code != 200:
        return {"error": response.text}

    data = response.json()
    results = [
        {
            "title": item["title"],
            "snippet": item["snippet"],
            "link": item["link"]
        }
        for item in data.get("items", [])
    ]
    return results

if __name__ == "__main__":
    print("Running Google Search MCP...", file=sys.stderr)
    mcp.run(transport="stdio")

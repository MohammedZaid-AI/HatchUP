from langchain_tavily import TavilySearch
from mcp.server import FastMCP
import os
import sys
from dotenv import load_dotenv

mcp = FastMCP("Tavily Search MCP")

load_dotenv()
api_key = os.getenv("TAVILY_API_KEY")
tavily_client = TavilySearch(api_key=api_key) if api_key else None


@mcp.tool()
def tavily(query: str):
    if not tavily_client:
        return {"error": "TAVILY_API_KEY is not configured."}
    cleaned_query = (query or "").replace("tavily:", "").strip()
    if not cleaned_query:
        return {"error": "Query is empty."}
    return tavily_client.run(cleaned_query)


if __name__ == "__main__":
    print("Running Tavily Search MCP...", file=sys.stderr)
    mcp.run(transport="stdio")

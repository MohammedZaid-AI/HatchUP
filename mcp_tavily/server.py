from langchain_tavily import TavilySearch
from mcp.server import FastMCP
import os
import sys
from dotenv import load_dotenv

mcp = FastMCP("Tavily Search MCP")

load_dotenv()
api_key =os.environ["TAVILY_API_KEY"]=os.getenv("TAVILY_API_KEY")

tavily = TavilySearch(api_key=api_key)

@mcp.tool()
def tavily(query: str):
    cleaned_query = query.replace("tavily:", "").strip()  # Remove the prefix if present
    results = tavily.run(cleaned_query)
    return results

if __name__ == "__main__":
    print("Running Tavily Search MCP...", file=sys.stderr)
    mcp.run(transport="stdio")

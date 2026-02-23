from fastapi import APIRouter, HTTPException, Body, Request, Response
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from functools import lru_cache
import os
from pathlib import Path
import json
import asyncio
from dotenv import load_dotenv
from src.services.analysis_service import AnalysisService
from src.session import ensure_session_id, get_active_analysis_id, set_active_analysis_id

# LangChain Imports
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from mcp_use import MCPClient
import sys

# Load environment logic from HatchUp_chat.py regarding secrets is not needed in FastAPI 
# as we expect .env or system env vars to be set.
load_dotenv()

router = APIRouter()


@lru_cache(maxsize=1)
def get_analysis_service() -> AnalysisService:
    return AnalysisService()

# --- Models ---
class Message(BaseModel):
    role: str
    content: str

class ResearchRequest(BaseModel):
    messages: List[Message]
    data: Optional[Dict[str, Any]] = None  # PitchDeckData
    memo: Optional[Dict[str, Any]] = None  # InvestmentMemo

class ChatRequest(BaseModel):
    messages: List[Message]
    query: str

# --- Deep Research Logic ---
@router.post("/api/chat/research")
async def deep_research(payload: ResearchRequest, request: Request, response: Response):
    """
    RAG-based chat on the Pitch Deck Data and Investment Memo.
    Replicates pages/2_Research_Engine.py
    """
    try:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="GROQ_API_KEY not found")

        data_obj = payload.data
        memo_obj = payload.memo
        analysis_id = get_active_analysis_id(request)
        if not data_obj:
            session_id = ensure_session_id(request, response)
            service = get_analysis_service()
            active = service.get_or_create_active_analysis(
                user_id=session_id,
                active_analysis_id=get_active_analysis_id(request),
            )
            analysis_id = active["analysis_id"]
            data_obj = active.get("deck")
            memo_obj = active.get("memo") or {}
            set_active_analysis_id(response, analysis_id)
        if not data_obj:
            raise HTTPException(status_code=400, detail="No active deck analysis found")

        # Reconstruct context
        data_json = json.dumps(data_obj, indent=2)
        memo_json = json.dumps(memo_obj or {}, indent=2)

        context_str = f"""
        *** STARTUP ANALYZED DATA ***
        {data_json}
        
        *** INVESTMENT MEMO ***
        {memo_json}
        """

        system_prompt = """You are a highly intelligent VC Research Associate. 
        You have access to the parsed Pitch Deck Data and a generated Investment Memo for a startup.
        
        Your goal is to answer the User's (Partner's) questions deeply and critically.
        
        Guidelines:
        1. Use the provided Context as your primary source.
        2. If the user asks for validation (e.g. Market size, competitors), use your own internal knowledge to verify if the startup's claims are realistic.
        3. Be concise but insightful. Start directly with the answer.
        4. If drafting emails, use a professional VC tone.
        
        FORMATTING RULES (CRITICAL):
        - Format your response as a clean, executive-style memo.
        - Avoid Markdown tables. 
        - Use clear uppercase or bold HEADERS for sections.
        - Use short, sharp bullet points for lists.
        - Keep language professional, simple, and direct.
        - Focus on actionable insights.
        - Ensure clean spacing between sections.
        - Do NOT use academic grid structures or complex markdown.
        """

        # Get last user message
        user_query = payload.messages[-1].content

        llm = ChatGroq(
            temperature=0.5,
            model_name="openai/gpt-oss-20b", 
            groq_api_key=api_key
        )

        prompt_template = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", "Context:\n{context}\n\nQuestion: {question}")
        ])

        chain = prompt_template | llm
        
        # We will return the full response string (not streaming for simplicity in this MVP migration phase 1)
        # If streaming is needed, we'd use StreamingResponse
        llm_response = await chain.ainvoke({"context": context_str, "question": user_query})
        
        return {"response": llm_response.content, "analysis_id": analysis_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- HatchUp Chat Logic (MCP) ---
# Initialize MCP Client Global State
mcp_sessions = None
mcp_client = None

async def get_mcp_sessions():
    global mcp_sessions, mcp_client
    if mcp_sessions:
        return mcp_sessions
    
    # Initialize Client
    base_dir = Path(__file__).parent.parent.resolve() # routers/ -> root/
    
    # Prepare Config
    # Check if directories exist
    mcp_dirs = {
        "reddit": base_dir / "mcp_reddit" / "server.py",
        "wiki": base_dir / "mcp_wiki" / "server.py",
        "google": base_dir / "mcp_google" / "server.py",
        "medium": base_dir / "mcp_medium" / "server.py"
    }
    
    # Validate existence
    for k, v in mcp_dirs.items():
        if not v.exists():
             print(f"Warning: MCP server script not found at {v}")

    server_config = {
        "mcpServers": {
            "@echolab/mcp-reddit": {
                "command": sys.executable,
                "args": [str(mcp_dirs["reddit"])]
            },
            "@echolab/mcp-wikipedia": {
                "command": sys.executable,
                "args": [str(mcp_dirs["wiki"])]
            },
            "@echolab/mcp-google": {
                "command": sys.executable,
                "args": [str(mcp_dirs["google"])]
            },
            "@echolab/mcp-medium": {
                "command": sys.executable,
                "args": [str(mcp_dirs["medium"])]
            }
        }
    }
    
    # Write temp config
    temp_config_path = base_dir / "config_dynamic_fastapi.json"
    with open(temp_config_path, "w") as f:
        json.dump(server_config, f, indent=2)
        
    mcp_client = MCPClient.from_config_file(str(temp_config_path))
    mcp_sessions = await mcp_client.create_all_sessions()
    return mcp_sessions

async def run_searches(query: str, sessions):
    """
    Runs live searches using MCP tools. Returns a dictionary of results.
    """
    def fail(name, e):
        return f"[{name} MCP Error: {str(e)}]"

    results = {}
    
    # Run in parallel if possible, but sessions might not be thread safe? 
    # MCP sessions usually async safe.
    
    # 1. Reddit
    try:
        results["reddit"] = await sessions["@echolab/mcp-reddit"].call_tool(
            "fetch_reddit_posts_with_comments", 
            {"subreddit": "startups", "limit": 1} 
        )
    except Exception as e:
        results["reddit"] = fail("Reddit", e)

    # 2. Wikipedia
    try:
        results["wiki"] = await sessions["@echolab/mcp-wikipedia"].call_tool(
            "search", {"query": query}
        )
    except Exception as e:
        results["wiki"] = fail("Wikipedia", e)

    # 3. Google
    try:
        results["google"] = await sessions["@echolab/mcp-google"].call_tool(
            "google_search", {"query": query}
        )
    except Exception as e:
        results["google"] = fail("Google", e)

    # 4. Medium
    try:
        results["medium"] = await sessions["@echolab/mcp-medium"].call_tool(
            "search_medium", {"query": query}
        )
    except Exception as e:
        results["medium"] = fail("Medium", e)

    return results

def build_context_string(results: dict) -> str:
    def truncate(content, limit=2000):
        s = str(content)
        return s[:limit] + "... [TRUNCATED]" if len(s) > limit else s

    return f"""
    --- SEARCH RESULTS ---
    [Reddit]: {truncate(results.get("reddit"))}
    [Wikipedia]: {truncate(results.get("wiki"))}
    [Google]: {truncate(results.get("google"))}
    [Medium]: {truncate(results.get("medium"))}
    ----------------------
    """

@router.post("/api/chat/hatchup")
async def hatchup_chat(request: ChatRequest):
    """
    MCP-based Chat.
    """
    try:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="GROQ_API_KEY not found")

        sessions = await get_mcp_sessions()
        
        # Run Searches
        search_results = await run_searches(request.query, sessions)
        context_str = build_context_string(search_results)
        
        # Prepare Prompt
        history_text = "\n".join([f"{m.role.upper()}: {m.content}" for m in request.messages[-5:]])
        
        llm = ChatGroq(
            model="openai/gpt-oss-20b",
            temperature=0.3,
            groq_api_key=api_key
        )
        
        chat_prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                """
                You are HatchUp Chat, a smart VC research assistant.
                
                BEHAVIOR:
                1. If the user says "Hello" or engages in small talk, reply conversationally.
                2. If the user asks a specific question or topic, use the provided [Context] to generate a analysis.
                3. IGNORE error messages in the context.
                4. Do NOT hallucinate.
                
                FORMATTING RULES (CRITICAL):
                - Format your response as a clean, executive-style strategy memo.
                - Use clear uppercase or bold HEADERS for sections (e.g. "KEY INSIGHTS", "MARKET SIGNALS").
                - Use short, punchy bullet points.
                - Focus on actionable insights.
                - Do NOT use markdown tables or complex grids.
                - Keep spacing clean and readable.
                """
            ),
            (
                "human",
                """
                [Context from Live Tools]
                {context}

                [Conversation History]
                {history}

                [Current User Input]
                {question}
                """
            )
        ])
        
        messages = chat_prompt.format_messages(
            context=context_str,
            history=history_text,
            question=request.query
        )
        
        response = await llm.ainvoke(messages)
        
        return {
             "response": response.content,
             "sources": search_results # Optional: return sources for UI to show
        }

    except Exception as e:
        # In case of error (e.g. MCP failed), return error
        raise HTTPException(status_code=500, detail=str(e))

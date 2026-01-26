import streamlit as st
import os
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

st.set_page_config(
    page_title="Deep Research - HatchUp",
    page_icon="🔎",
    layout="wide"
)

st.title("🔎 Deep Research Engine")
st.markdown("Ask complex questions about the startup, validate claims, or generate specific correspondence based on the analyzed data and memo.")

# Check for data
if "analysis_result" not in st.session_state or not st.session_state.analysis_result:
    st.info("No analysis data found. Please Go to 'Pitch Deck Analyzer' or 'Create Memo' to load data first.")
    st.stop()

# Get Data
data = st.session_state.analysis_result.get("data")
memo = st.session_state.analysis_result.get("memo")

if not data or not memo:
    st.warning("Incomplete data. Ensure both Pitch Deck Data and Investment Memo are generated.")
    st.stop()

# Initialize Chat History
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display Chat History
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- Sidebar: Ready Queries ---
st.sidebar.title("💡 Ready Queries")
st.sidebar.markdown("Click to copy/ask:")

queries = [
    "What are the 3 biggest risks not mentioned in the deck?",
    "Evaluate the team's ability to execute this specific solution.",
    "Is the TAM calculated realistically? validate it.",
    "Compare this to major competitors.",
    "Draft a follow-up email asking about their unit economics.",
    "Draft a polite pass (rejection) email.",
    "What specific questions should I ask in the partner meeting?"
]

def set_query(q):
    st.session_state._input_query = q

for q in queries:
    if st.sidebar.button(q, use_container_width=True):
        # We can either immediately send it or put it in the input
        # Putting it in session state to pre-fill or triggering directly is tricky in Streamlit.
        # Best way: Add to messages and trigger run.
        st.session_state.messages.append({"role": "user", "content": q})
        st.rerun()

# --- Chat Input ---
if prompt := st.chat_input("Ask a question about this startup..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.rerun()

# --- Generate Response ---
# Check if the last message is from user, if so, generate response
if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    user_query = st.session_state.messages[-1]["content"]
    
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        try:
            llm = ChatGroq(
                temperature=0.5,
                model_name="openai/gpt-oss-20b", 
                groq_api_key=os.environ.get("GROQ_API_KEY"),
                streaming=True
            )
            
            context_str = f"""
            *** STARTUP ANALYZED DATA ***
            {data.model_dump_json()}
            
            *** INVESTMENT MEMO ***
            {memo.model_dump_json()}
            """
            
            system_prompt = """You are a highly intelligent VC Research Associate. 
            You have access to the parsed Pitch Deck Data and a generated Investment Memo for a startup.
            
            Your goal is to answer the User's (Partner's) questions deeply and critically.
            
            Guidelines:
            1. Use the provided Context as your primary source.
            2. If the user asks for validation (e.g. Market size, competitors), use your own internal knowledge to verify if the startup's claims are realistic.
            3. Be concise but insightful. Start directly with the answer.
            4. If drafting emails, use a professional VC tone.
            """
            
            prompt_template = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("user", "Context:\n{context}\n\nQuestion: {question}")
            ])
            
            chain = prompt_template | llm
            
            # Stream response
            for chunk in chain.stream({"context": context_str, "question": user_query}):
                if chunk.content:
                    full_response += chunk.content
                    message_placeholder.markdown(full_response + "▌")
            
            message_placeholder.markdown(full_response)
            
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            st.error(f"Error requesting reasoning: {e}")

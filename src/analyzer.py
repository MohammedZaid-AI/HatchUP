from typing import Optional
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from src.models import PitchDeckData
import os

class PitchDeckAnalyzer:
    def __init__(self, api_key: str, model_name: str = "openai/gpt-oss-20b"):
        self.llm = ChatGroq(
            temperature=0,
            model_name=model_name,
            groq_api_key=api_key
        )

    def analyze_pitch_deck(self, deck_text: str) -> PitchDeckData:
        """
        Analyzes the full text of a pitch deck and extracts structured insights.
        """
        
        # We will use PydanticOutputParser to ensure strictly formatted JSON
        parser = PydanticOutputParser(pydantic_object=PitchDeckData)
        
        system_prompt = """You are a cynical, analytical, and highly structured Junior VC Analyst.
your goal is to extract key due diligence information from a startup pitch deck.
Be objective. If a section is missing, explicitly state it is missing.
Identify vague claims (weak signals) and potential risks (red flags).

Output must be valid JSON matching the schema provided."""

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", "Extract information from this pitch deck text:\n\n{text}\n\n{format_instructions}")
        ])

        chain = prompt | self.llm | parser
        
        try:
            result = chain.invoke({
                "text": deck_text,
                "format_instructions": parser.get_format_instructions()
            })
            return result
        except Exception as e:
            # Fallback or error handling
            print(f"Error extracting data: {e}")
            raise e

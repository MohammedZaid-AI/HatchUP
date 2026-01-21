from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from src.models import PitchDeckData, InvestmentMemo, ExecutiveSummary

class MemoGenerator:
    def __init__(self, api_key: str, model_name: str = "openai/gpt-oss-20b"):
        self.llm = ChatGroq(
            temperature=0.3, # Slightly creative for writing but still grounded
            model_name=model_name,
            groq_api_key=api_key
        )
    
    def generate_memo(self, data: PitchDeckData) -> InvestmentMemo:
        """
        Generates a professional Investment Memo based on the extracted data.
        """
        parser = PydanticOutputParser(pydantic_object=InvestmentMemo)
        
        system_prompt = """You are a professional VC Partner writing an internal investment memo.
Tone: Professional, objective, analytical, non-hyped.
Format: YC-style investment memo.
Use the structured data provided to write detailed sections.
Highlight missing info clearly."""

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", "Here is the extracted startup data:\n{data}\n\nWrite a full investment memo.\n{format_instructions}")
        ])

        chain = prompt | self.llm | parser
        
        return chain.invoke({
            "data": data.model_dump_json(),
            "format_instructions": parser.get_format_instructions()
        })

    def generate_executive_summary(self, data: PitchDeckData, memo: InvestmentMemo) -> ExecutiveSummary:
        """
        Generates a concise Executive Summary (30-second read).
        """
        parser = PydanticOutputParser(pydantic_object=ExecutiveSummary)
        
        system_prompt = """You are a VC Associate summarizing a deal for a General Partner.
The summary must be readable in under 30 seconds.
Format:
- 5-7 punchy bullet points.
- A final decision outlook (Neutral/Positive/Negative) based on the data.
Avoid fluff."""

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", "Data: {data}\nMemo Highlights: {memo}\n\nGenerate Executive Summary.\n{format_instructions}")
        ])

        chain = prompt | self.llm | parser
        
        return chain.invoke({
            "data": data.model_dump_json(),
            "memo": memo.model_dump_json(),
            "format_instructions": parser.get_format_instructions()
        })

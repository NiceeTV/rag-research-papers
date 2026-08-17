import pdfplumber
import json
import re
from pathlib import Path
import requests


def extract_pdf_content(pdf_path: str) -> dict:
    """
        Extracts text and tables from PDF. Returns dict with pages such as:
        - text: text of the page
        - tables: extracted tables
    """
    result = {
        "pages": [],
        "tables": [],
        "metadata": {"total_pages": 0}
    }

    with pdfplumber.open(pdf_path) as pdf:
        result["metadata"]["total_pages"] = len(pdf.pages) #number of pages in pdf

        for page_num, page in enumerate(pdf.pages, start=1): #go through each page
            #extract text
            text = page.extract_text()

            print("text", text)

            #extract tables
            tables = page.extract_tables()

            print("tabulky",tables)

            #save tables with metadata if they exist
            if tables:
                for table in tables:
                    if table:  # nie prázdna tabuľka
                        result["tables"].append({
                            "page": page_num,
                            "data": table,
                            "raw_text": page.extract_text() #context for llm about the table
                        })

            result["pages"].append({
                "page_number": page_num,
                "text": text,
                "tables_count": len(tables) if tables else 0
            })

    return result


if __name__ == "__main__":
    #"attention is all you need" paper
    pdf_path = "../data/raw/attention_is_all_you_need.pdf"

    #if it does not exist, download it from the internet
    if not Path(pdf_path).exists():
        Path("../data/raw").mkdir(parents=True, exist_ok=True) #create dir if it does not exist
        url = "https://arxiv.org/pdf/1706.03762.pdf"
        response = requests.get(url)
        with open(pdf_path, "wb") as f: #write to path
            f.write(response.content)
        print(f"Saved PDF to {pdf_path}")

    #extract content
    content = extract_pdf_content(pdf_path)

    #save to JSON
    with open("../data/extracted_content.json", "w", encoding="utf-8") as f:
        json.dump(content, f, indent=2, ensure_ascii=False)

    print(f"Extracted: {len(content['pages'])} pages, {len(content['tables'])} tables")
    print("First table:")
    if content["tables"]:
        print(content["tables"][0]["data"][:3]) #first 3 lines
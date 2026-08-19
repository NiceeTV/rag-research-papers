import json
import re

def merge_pages(json_doc: dict) -> str:
    """
        Merge all page texts into 1 string.
    """
    full_text = ""

    #check if doc has "pages" key
    if "pages" not in json_doc:
        raise ValueError("Dokument neobsahuje 'pages' kľúč")

    for page in json_doc["pages"]:
        #every page is a dict with "text" key
        text = page.get("text", "")
        if text:
            full_text += text + "\n\n"

    return full_text


def detect_heading_patterns(text: str) -> list:
    """
        Find all lines that look like Headings.
    """
    lines = text.split('\n')
    headings = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        #Multiline header such as "1\nIntroduction" as seen in text
        if re.match(r'^\d+$', line): #"1", "2", "3"
            j = i + 1
            while j < len(lines) and lines[j].strip() == '':
                j += 1

            if j < len(lines):
                next_line = lines[j].strip()
                if re.match(r'^[A-Z][a-z]+', next_line) and len(next_line) < 60:
                    full_heading = f"{line} {next_line}"

                    #calculate position from the line index
                    position = sum(len(lines[k]) + 1 for k in range(i))  # +1 pre \n
                    headings.append({
                        "line": full_heading,
                        "index": i,
                        "position": position
                    })
                    i = j + 1
                    continue

        #numbered header such as 3.1 Results
        if re.match(r'^\d+\.\d+$', line):  # "3.1"
            j = i + 1
            while j < len(lines) and lines[j].strip() == '':
                j += 1

            if j < len(lines):
                next_line = lines[j].strip()
                if re.match(r'^[A-Z][a-z]+', next_line) and len(next_line) < 60:
                    full_heading = f"{line} {next_line}"
                    position = sum(len(lines[k]) + 1 for k in range(i))
                    headings.append({
                        "line": full_heading,
                        "index": i,
                        "position": position
                    })
                    i = j + 1
                    continue

        #common headers without numbers from articles
        common_pattern = r'^\s*(Abstract|Introduction|Related\s+Work|Methodology|Results|Discussion|Conclusion|References|Acknowledgements|Appendix|Supplementary)\s*$'
        if re.match(common_pattern, line, re.IGNORECASE):
            position = sum(len(lines[k]) + 1 for k in range(i))
            headings.append({
                "line": line,
                "index": i,
                "position": position
            })
            i += 1
            continue

        #all caps headers
        if re.match(r'^\s*[A-Z\s]{3,50}\s*$', line):
            if len(line) > 3 and line.isupper():
                position = sum(len(lines[k]) + 1 for k in range(i))
                headings.append({
                    "line": line,
                    "index": i,
                    "position": position
                })
            i += 1
            continue

        i += 1

    return headings


def chunk_by_headings(text: str, headings: list, min_chunk_size: int = 500) -> list:
    """
        Divide text by headers and merge small chunks to min_size.
    """
    #divide by headers
    raw_chunks = []
    for i, heading in enumerate(headings):
        start = heading['position']
        end = headings[i + 1]['position'] if i + 1 < len(headings) else len(text)
        content = text[start:end].strip()

        raw_chunks.append({
            "content": content,
            "heading": heading['line'],
            "size": len(content)
        })

    #merge smaller chunks
    merged_chunks = []
    buffer = ""
    current_heading = None

    for chunk in raw_chunks:
        if current_heading is None:
            current_heading = chunk['heading']

        buffer += chunk['content'] + "\n\n"

        #if the buffer is big enough, save
        if len(buffer) >= min_chunk_size:
            merged_chunks.append({
                "content": buffer.strip(),
                "heading": current_heading,
                "size": len(buffer)
            })
            buffer = ""
            current_heading = None

    #last buffer if not empty
    if buffer:
        merged_chunks.append({
            "content": buffer.strip(),
            "heading": current_heading or "Last section",
            "size": len(buffer)
        })

    return merged_chunks


if __name__ == "__main__":
    #"attention is all you need" extracted json
    extracted_path = "extracted_document.json"

    with open(extracted_path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    #merge page text and chunk it semantically
    merged_text = merge_pages(doc)
    #print(merged_text[:3000])

    #find headings
    headings = detect_heading_patterns(merged_text)
    print("headings",headings)

    merged_chunks = chunk_by_headings(merged_text, headings)
    for c in merged_chunks:
        print(f"Header: '{c["heading"]}', size: '{c["size"]}', chunk: {c}")

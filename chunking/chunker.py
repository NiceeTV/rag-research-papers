import json
import re
import pandas as pd

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

        #multiline header such as "1\nIntroduction" as seen in text
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


def chunk_large_table(df, caption: str, table_id: str, max_tokens: int = 1500, max_rows: int = 20) -> list:
    """
        Divide oversized table to smaller chunks.
    """
    chunks = []
    num_rows = len(df)

    #if it is small, return as 1 chunk
    if num_rows <= max_rows or len(caption) + len(df.to_markdown()) < max_tokens * 4:
        markdown = df.to_markdown(index=False)
        chunks.append({
            "content": f"{markdown}",
            "heading": caption,
            "type": "table",
            "table_id": table_id,
            "part": 1,
            "total_parts": 1
        })
        return chunks

    #divide by rows
    total_parts = (num_rows + max_rows - 1) // max_rows
    for i in range(0, num_rows, max_rows):
        part_num = i // max_rows + 1
        chunk_df = df.iloc[i:i + max_rows]
        markdown = chunk_df.to_markdown(index=False)
        chunk_caption = f"{caption} (rows {i + 1}-{min(i + max_rows, num_rows)})"

        chunks.append({
            "content": f"{chunk_caption}\n\n{markdown}",
            "heading": chunk_caption,
            "type": "table",
            "table_id": table_id,
            "part": part_num,
            "total_parts": total_parts
        })

    return chunks


def chunk_content(text: str, headings: list, tables: list, min_tokens: int = 200, max_tokens: int = 1500, token_overlap=50) -> list:
    """
        Divide text by headers and merge small chunks to min_size.
    """
    #min max size of chunk in tokens, appr. 1 token = 4 chars as per OpenAI
    min_chars = min_tokens * 4 #200 tokens = 800 chars
    max_chars = max_tokens * 4 #1500 tokens = 6000 chars

    #divide by headers
    raw_chunks = []
    for i, heading in enumerate(headings):
        start = heading['position']
        end = headings[i + 1]['position'] if i + 1 < len(headings) else len(text)
        content = text[start:end].strip()

        raw_chunks.append({
            "content": content,
            "heading": heading['line'],
            "size": len(content),
            "tokens": len(content) // 4
        })

    #merge smaller chunks
    merged_chunks = []
    buffer = ""
    overlap_content = ""
    current_heading = None

    for chunk in raw_chunks:
        if current_heading is None:
            current_heading = chunk['heading']

        #add chunk content to buffer
        buffer += chunk['content'] + "\n\n"

        #if the buffer is big enough, save
        if len(buffer) >= min_chars:

            #check if it is too large
            first_division = True
            if len(buffer) > max_chars:

                #keep dividing buffer while it is bigger than max_chars (max_tokens * 4)
                while len(buffer) > max_chars:

                    #do not overlap first part of the chunk, we do not want overlap from previous Section
                    if len(merged_chunks) > 0 and not first_division:
                        overlap_size = min(len(merged_chunks[-1]["content"]), token_overlap*4)
                        print("last chunk", merged_chunks[-1]["content"], overlap_size)
                        overlap_content = merged_chunks[-1]["content"][-overlap_size:]

                    #add overlapped chunk to merged_chunks
                    overlapped_chunk = overlap_content + buffer[:max_chars]
                    merged_chunks.append({
                        "content": overlapped_chunk.strip(),
                        "heading": current_heading,
                        "type": "text",
                        "size": max_chars,
                        "tokens": max_tokens
                    })

                    #cut buffer by max_chars
                    buffer = buffer[max_chars:]
                    first_division = False

                #last division of the big chunk
                if len(merged_chunks) > 0:
                    overlap_size = min(len(merged_chunks[-1]["content"]), token_overlap * 4)
                    overlap_content = merged_chunks[-1]["content"][-overlap_size:]

                #add last part of the oversized chunk
                overlapped_chunk = overlap_content + buffer[:max_chars]
                merged_chunks.append({
                    "content": overlapped_chunk.strip(),
                    "heading": current_heading,
                    "type": "text",
                    "size": len(overlapped_chunk),
                    "tokens": len(overlapped_chunk) // 4
                })

            #if the buffer is not oversized, just add it no overlap
            else:
                merged_chunks.append({
                    "content": buffer.strip(),
                    "heading": current_heading,
                    "type": "text",
                    "size": len(buffer),
                    "tokens": len(buffer) // 4
                })

            buffer = ""
            current_heading = None

    #last buffer if not empty
    if buffer:
        merged_chunks.append({
            "content": buffer.strip(),
            "heading": current_heading or "Last section",
            "size": len(buffer),
            "tokens": len(buffer) // 4
        })

    if tables:
        for table in tables:
            df = pd.DataFrame(table["data"])
            table_id = table.get('id', 'unknown')
            caption = table.get("caption", f"Table {table_id}")

            #chunk large tables
            table_chunks = chunk_large_table(df, caption, table_id, max_tokens=max_tokens)

            #add table chunks to text chunks
            for tc in table_chunks:
                merged_chunks.append({
                    "heading": tc["heading"],
                    "content": tc["content"],
                    "type": "table",
                    "page": table.get("page"),
                    "table_id": tc["table_id"],
                    "part": tc["part"],
                    "total_parts": tc["total_parts"],
                    "size": len(tc["content"]),
                    "tokens": len(tc["content"]) // 4
                })

    return merged_chunks


def save_chunks(chunks: list, output_path: str = "../chunking/chunks.json"):
    """
        Save chunks to JSON.
    """
    #serialize only valid chunks
    serializable_chunks = []
    for chunk in chunks:
        try:
            serializable_chunks.append({
                "content": chunk["content"],
                "heading": chunk.get("heading", "unknown"),
                "type": chunk.get("type", "text"), #text is default
                "page": chunk.get("page"),
                "table_id": chunk.get("table_id"),
                "part": chunk.get("part"),
                "total_parts": chunk.get("total_parts"),
                "size": chunk.get("size", len(chunk["content"])),
                "tokens": chunk.get("tokens", len(chunk["content"]) // 4)
            })
        except Exception as e:
            print(f"Error while processing chunk: {e}")
            print(f"   Chunk: {chunk}")
            continue

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable_chunks, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(serializable_chunks)} chunks to {output_path}.")
    return serializable_chunks


if __name__ == "__main__":
    #"attention is all you need" extracted json
    extracted_path = "extracted_document.json"

    with open(extracted_path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    #merge page text and chunk it semantically
    merged_text = merge_pages(doc)

    tables_from_doc = []
    for page in doc["pages"]:
        for table in page["tables"]:
            tables_from_doc.append({
                "page": page["page"],
                "id": table["id"],
                "caption": table.get("caption", ""),
                "data": table["data"]
            })

    #find headings
    headings = detect_heading_patterns(merged_text)
    print("headings",headings)

    merged_chunks = chunk_content(merged_text, headings, tables_from_doc)
    for c in merged_chunks:
        print(f"Header: '{c["heading"]}', tokens: '{c["tokens"]}', chunk: {c}")

    #save chunks to file
    save_chunks(merged_chunks)
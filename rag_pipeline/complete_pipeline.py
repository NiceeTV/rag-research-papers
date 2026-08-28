import os

from dotenv import load_dotenv
from pymupdf import pymupdf

from chunking.chunker import merge_pages, detect_heading_patterns, chunk_content
from embedding.embedder import create_embeddings_and_store, search_chunks
from ingestion.pdf_camelot_final_parser import extract_tables, extract_text, save_extracted_data
from llm_integration.llm_integration import ask_with_context

class RAG_pipeline:
    def __init__(self, embedder, llm, chroma_db_path, socketio):
        self.collection = None
        self.embedder = embedder
        self.llm = llm
        self.chroma_db = chroma_db_path
        self.socketio = socketio
        self.chunk_revelance_threshold = 0.5


    def send_ws_state(self, state:str = "unknown", part:int = 1):
        self.socketio.emit("pipeline-status",{
            "state":state,
            "part": part
        })


    def run_pipeline(self, pdf_path):
        ## INGESTION
        #open pdf with pymupdf
        print("Ingesting")
        self.send_ws_state("Ingesting", 1)

        doc = pymupdf.open(pdf_path)
        table_data = extract_tables(pdf_path, doc) #extract tables
        text_by_page = extract_text(table_data, doc) #extract text outside of tables

        doc = save_extracted_data(
            pdf_path=pdf_path,
            text_by_page=text_by_page,
            table_data=table_data,
            save_to_file=False
        )

        ## CHUNKING
        print("Chunking")
        self.send_ws_state("Chunking", 2)
        #merge page text and chunk it semantically
        merged_text = merge_pages(doc)

        #extract tables from all pages
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
        print("Detected headings:", headings)

        merged_chunks = chunk_content(merged_text, headings, tables_from_doc)

        #embedding
        print("Embedding")
        self.send_ws_state("Embedding", 3)
        #create embeddings and save to db
        client, collection = create_embeddings_and_store(merged_chunks, self.embedder, self.chroma_db)
        self.collection = collection
        print("Pipeline finished")
        self.send_ws_state("Finished")


    def ask_context(self, query):
        results = search_chunks(query, self.collection, self.embedder)

        print("results of ask", results)

        documents = results['documents'][0]
        metadata = results['metadatas'][0]
        distances = results['distances'][0]

        #discard if no good chunks are found
        filtered = []
        context = ""
        for doc, meta, dist in zip(documents, metadata, distances):
            if dist <= self.chunk_revelance_threshold:
                filtered.append({
                    "content": doc,
                    "metadata": meta,
                    "distance": dist
                })

                context += doc + "\n\n---\n\n"

        #no good chunks were found
        if not filtered:
            return {
                "query": query,
                "answer": "I don't know based on the provided documents.",
                "sources": []
            }

        token_appr = len(context) // 4
        if token_appr > 4096:
            return {
                "query": query,
                "answer": "This question exceeds the model context.",
                "sources": [],
            }

        else:
            sources = []
            for m in metadata:
                sources.append(m.get("heading", "unknown"))

            #init stream
            self.socketio.emit('answer-start', {"query": query, "sources": sources})

            ask_with_context(self.llm, self.socketio, query, context)

            #end stream
            self.socketio.emit('answer-done', {})

            return None


if __name__ == '__main__':
    # "attention is all you need" paper
    """pdf_path = r"../data/raw/attention_is_all_you_need.pdf"

    #load HF token
    load_dotenv()
    HF_TOKEN = os.getenv("HF_TOKEN")

    ## INGESTION
    print("\n## INGESTION ##\n")
    #open pdf with pymupdf
    doc = pymupdf.open(pdf_path)

    print("Extracting tables.\n")
    table_data = extract_tables(pdf_path, doc) #extract tables

    print("Extracting text.\n")
    text_by_page = extract_text(table_data, doc) #extract text outside of tables

    #visualize final detections
    print("Creating a visualization.\n")
    visualize_bboxes(doc, table_data)

    doc = save_extracted_data(
        pdf_path=pdf_path,
        text_by_page=text_by_page,
        table_data=table_data,
        save_to_file=False
    )
    print("table data",table_data)
    print("\n\n")

    ## CHUNKING
    print("\n## CHUNKING ##\n")
    #merge page text and chunk it semantically
    merged_text = merge_pages(doc)

    #extract tables from all pages
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
    print("Detected headings:", headings)

    merged_chunks = chunk_content(merged_text, headings, tables_from_doc)
    for c in merged_chunks:
        print(f"Header: '{c["heading"]}', tokens: '{c["tokens"]}', chunk: {c}")

    print("\n")

    print("\n## EMBEDDING ##\n")

    #create embeddings and save to db
    client, collection, model = create_embeddings_and_store(merged_chunks)

    #test search
    print("\nTest search:")
    query = "What BLEU score did the Transformer achieve?"
    results = search_chunks(query, collection, model)


    print(f"\nQuestion: {query}")
    print(f"Found {len(results['documents'][0])} chunks:")

    for i, (doc, metadata, dist) in enumerate(zip(
            results['documents'][0],
            results['metadatas'][0],
            results['distances'][0]
    )):
        print(f"\n--- Chunk {i + 1} (distance: {dist:.4f}) ---")
        print(f"Heading: {metadata.get('heading', 'unknown')}")
        print(f"Type: {metadata.get('type', 'text')}")
        print(f"Page: {metadata.get('page', 0)}")
        print(f"Content: {doc[:200]}...")

    print("\n## LLM INTEGRATION ##\n")
    llm = load_llm()

    documents = results['documents'][0]
    context = "\n\n---\n\n".join(documents)

    answer = ask_with_context(llm, query, context)
    print(f"Answer: {answer}")"""
    pass
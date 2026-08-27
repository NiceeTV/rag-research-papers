import os
from dotenv import load_dotenv
import json

import chromadb
from chromadb.config import Settings


def load_embedder():
    import transformers
    transformers.logging.set_verbosity_info()
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("BAAI/bge-small-en-v1.5")
    return model


def load_chunks(chunks_path: str) -> list:
    """
        Load chunks from JSON.
    """
    with open(chunks_path, "r", encoding="utf-8") as f:
        return json.load(f)


def clean_metadata(metadata: dict) -> dict:
    """
    Nahradí None hodnoty v metadátach za prázdny reťazec.
    """
    cleaned = {}
    for key, value in metadata.items():
        if value is None:
            cleaned[key] = ""
        else:
            cleaned[key] = value
    return cleaned


def create_embeddings_and_store(chunks: list, model, db_path: str = "./chroma_db"):
    """
        Create chunk embeddings and store them in ChromaDB.
    """
    print("Embedding chunks.")
    #load embedding model
    #print("Loading embedding model.")
    #model = SentenceTransformer("BAAI/bge-small-en-v1.5")
    #print(f"   Model loaded, dimensions: {model.get_embedding_dimension()}")

    #prepare data for embedding
    texts = [chunk["content"] for chunk in chunks]
    metadatas = []
    ids = []

    #extract metadata from file
    for i, chunk in enumerate(chunks):
        raw_metadata = {
            "heading": chunk.get("heading", "unknown"),
            "type": chunk.get("type", "text"),
            "page": chunk.get("page", 0),
            "table_id": chunk.get("table_id"),
            "part": chunk.get("part"),
            "total_parts": chunk.get("total_parts"),
            "tokens": chunk.get("tokens", 0)
        }
        metadatas.append(clean_metadata(raw_metadata))
        ids.append(f"chunk_{i}")

    #generate embeddings
    print(f"Creating embeddings for {len(texts)} chunks.")
    embeddings = model.encode(texts, show_progress_bar=True)
    print(f"   Done, shape: {embeddings.shape}")

    #save results fo chromadb
    print(f"Saving to ChromaDB ({db_path}).")
    client = chromadb.PersistentClient(path=db_path, settings=Settings(anonymized_telemetry=False))

    #if collection already exists, delete it
    try:
        client.delete_collection("chunks")
    except:
        pass

    collection = client.create_collection(
        name="chunks",
        metadata={"hnsw:space": "cosine"} #cosine distance
    )

    #add chunks to collections
    collection.add(
        documents=texts,
        embeddings=embeddings.tolist(),
        metadatas=metadatas,
        ids=ids
    )

    print(f"Saved {collection.count()} chunks to ChromaDB")
    return client, collection


def search_chunks(query: str, collection, model, top_k: int = 3) -> dict:
    """
        Search relevant chunks for the question.
    """
    #create embeddings for question
    query_embedding = model.encode([query])[0]

    #search in db
    results = collection.query(
        query_embeddings=[query_embedding.tolist()],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )

    return results


if __name__ == "__main__":
    #load HF token
    """load_dotenv()
    HF_TOKEN = os.getenv("HF_TOKEN")

    #load chunks
    chunks = load_chunks("../chunking/chunks.json")
    print(f"Loaded {len(chunks)} chunks.")

    #create embeddings and save to db
    client, collection, model = create_embeddings_and_store(chunks, HF_TOKEN)

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
        print(f"Content: {doc[:200]}...")"""
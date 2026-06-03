import chromadb
from chromadb.utils import embedding_functions
import os

def load_docs_to_chroma():
    client = chromadb.PersistentClient(path="./chroma_db")
    
    embedding_fn = embedding_functions.DefaultEmbeddingFunction()
    
    collection = client.get_or_create_collection(
        name="prism_docs",
        embedding_function=embedding_fn
    )
    
    if collection.count() > 0:
        print("Docs already loaded, skipping.")
        return collection
    
    with open("prism_docs.txt", "r") as f:
        text = f.read()
    
    chunks = [chunk.strip() for chunk in text.split("\n\n") if chunk.strip()]
    
    collection.add(
        documents=chunks,
        ids=[f"chunk_{i}" for i in range(len(chunks))]
    )
    
    print(f"Loaded {len(chunks)} chunks into ChromaDB.")
    return collection


def retrieve_relevant_chunks(query, n_results=3):
    client = chromadb.PersistentClient(path="./chroma_db")
    embedding_fn = embedding_functions.DefaultEmbeddingFunction()
    
    collection = client.get_or_create_collection(
        name="prism_docs",
        embedding_function=embedding_fn
    )
    
    results = collection.query(
        query_texts=[query],
        n_results=n_results
    )
    
    return results["documents"][0]
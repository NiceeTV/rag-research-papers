from llama_cpp import Llama

def load_llm(llm_path):
    """
        Load llm model for answering questions.
    """
    print("Loading Llama 3.2...")
    llm = Llama(
        model_path=llm_path,
        n_ctx=4096,
        n_gpu_layers=-1,  #
        n_threads=6,
        verbose=False,
    )
    print("Model loaded.")
    return llm

def ask_with_context(llm, question: str, context: str) -> str:
    """
        Ask llm question using context.
    """
    prompt = f"""<|start_header_id|>system<|end_header_id|>
        Answer the question based on the context. If you don't know, say "I don't know".<|eot_id|>
        <|start_header_id|>user<|end_header_id|>
        Context:
        {context}
        
        Question: {question}<|eot_id|>
        <|start_header_id|>assistant<|end_header_id|>
    """

    response = llm(prompt, max_tokens=512, temperature=0.2, stop=["<|eot_id|>"])
    return response["choices"][0]["text"].strip()

if __name__ == "__main__":
    pass
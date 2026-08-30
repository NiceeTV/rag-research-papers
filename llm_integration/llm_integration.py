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
        verbose=True,
    )
    print("Model loaded.")
    return llm

def ask_with_context(llm, socketio, question: str, context: str):
    """
        Ask llm question using context.
    """
    prompt = f"""<|start_header_id|>system<|end_header_id|>
        You are a helpful assistant. You will be given a question and a context.
        Your task is to:
        1. First, determine if the context is relevant to the question.
        2. If the context is relevant, answer the question based ONLY on the context.
        3. If the context is NOT relevant, respond with: "I don't know based on the provided documents."
    
        Do not use any outside knowledge.<|eot_id|>
        <|start_header_id|>user<|end_header_id|>
        Context:
        {context}
    
        Question: {question}<|eot_id|>
        <|start_header_id|>assistant<|end_header_id|>"""
    answer = ""
    for token in llm.create_completion(
            prompt,
            max_tokens=512,
            temperature=0.2,
            stop=["<|eot_id|>"],
            stream=True,
            echo=False,
    ):
        # token je slovník
        if 'choices' in token and token['choices'][0].get('text'):
            chunk = token['choices'][0]['text']
            answer += chunk
            socketio.emit('answer-token', {'token': chunk})

    return answer

if __name__ == "__main__":
    pass
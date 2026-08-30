import base64
import gc
import json
import shutil
import sys
import time
import os
import uuid
from datetime import datetime
import threading
from pathlib import Path
from typing import Any

import chromadb
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, join_room

from embedding.embedder import load_embedder
from llm_integration.llm_integration import load_llm
from rag_pipeline.complete_pipeline import RAG_pipeline


app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['TEMPLATES_AUTO_RELOAD'] = True #refresh template when changed so we dont have to reset server everytime
socketio = SocketIO(app,
                    cors_allowed_origins="*",
                    ping_timeout=3600,
                    max_http_buffer_size=50 * 1024 * 1024, #50 MB buffer
                    ping_interval=25
                    )

#folder names
SESSION_FOLDER = 'sessions'
UPLOAD_FOLDER = 'uploads'

#create upload and session folders if they dont exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SESSION_FOLDER, exist_ok=True)


rag_pipelines = {}
models_loaded = False

@socketio.on('connect')
def handle_connect():
    print('Client connected:', request.sid)

    sessions = get_all_sessions()
    socketio.emit('connected', {'message': 'Connected to server', "models_ready": models_loaded, 'sessions': sessions})

@app.route('/')
def index():
    return render_template('index.html') #main page

uploads = {}

#upload limits
MAX_FILE_SIZE = 50 * 1024 * 1024 #50 MB
CHUNK_SIZE = 512 * 1024 #512 KB chunks

#session management
def get_session_path(session_id: str) -> Path:
    """
        Get path of the session folder.
    """
    return Path(f"./sessions/{session_id}")

def get_session_info_path(session_id: str) -> Path:
    """
        Get session_info path from the session folder.
    """
    return get_session_path(session_id) / "session_info.json"

def load_session_info(session_id: str) -> Any | None:
    """
        Get session_info.
    """
    path = get_session_info_path(session_id)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def save_session_info(session_id: str, info: dict):
    """
        Save updated session_info to session.
    """
    path = get_session_info_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    info["updated_at"] = datetime.now().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)

def add_message(session_id: str, role: str, text: str, sources: list = None):
    """
        Add message to chat_history.
    """
    info = load_session_info(session_id)
    if info is None:
        info = {
            "session_id": session_id,
            "file_name": "unknown",
            "messages": []
        }

    if "messages" not in info:
        info["messages"] = []

    info["messages"].append({
        "role": role,
        "text": text,
        "sources": sources or [],
        "timestamp": datetime.now().isoformat()
    })
    save_session_info(session_id, info)

@socketio.on('load-session')
def handle_load_session(data):
    """
        Send session info to frontend.
    """
    session_id = data['session_id']
    info = load_session_info(session_id)
    if info:
        socketio.emit('session-loaded', {
            'file_name': info.get('original_filename', 'unknown'),
            'messages': info.get('messages', []),
            'session_id': session_id
        })


#get session list
def get_all_sessions() -> list:
    """
        Returns session list with their metadata.
    """
    sessions = []
    sessions_path = Path("./sessions")

    if not sessions_path.exists():
        return sessions

    for session_path in sessions_path.iterdir():
        if session_path.is_dir():
            info_path = session_path / "session_info.json"
            if info_path.exists():
                try:
                    with open(info_path, "r", encoding="utf-8") as f:
                        info = json.load(f)
                    sessions.append({
                        "session_id": session_path.name,
                        "file_name": info.get("original_filename", info.get("stored_filename", "unknown")),
                        "created_at": info.get("created_at", ""),
                        "message_count": len(info.get("messages", [])),
                        "file_size": info.get("file_size", 0)
                    })
                except:
                    pass

    #sort by date
    sessions.sort(key=lambda x: x["created_at"], reverse=True)
    return sessions

@socketio.on('get-sessions')
def handle_get_sessions():
    sessions = get_all_sessions()
    socketio.emit('sessions-list', {'sessions': sessions})


#init llm and embedder
def load_models_background():
    """
        Loads models on thread.
    """
    global embedder, llm, models_loaded

    print("Loading models in the background...", flush=True)

    embedder = load_embedder()
    llm = load_llm("models/Llama-3.2-3B-Instruct-Q4_K_M.gguf")
    models_loaded = True

    print("Models loaded.", flush=True)
    socketio.emit('model-ready')

def run_rag_pipeline(session_id: str, pdf_path: str):
    """
        Run RAG pipeline for PDF file (ingestion, chunking, embedding).
    """
    try:
        session_path = Path(SESSION_FOLDER) / session_id
        session_path.mkdir(parents=True, exist_ok=True)

        #save pipeline
        rag_p = RAG_pipeline(
            chroma_db_path=str(session_path / "chroma_db"),
            llm=llm,
            embedder=embedder,
            socketio=socketio
        )

        rag_p.run_pipeline(pdf_path)
        rag_pipelines[session_id] = rag_p

        info = load_session_info(session_id) or {"session_id": session_id}
        info["file_size"] = str(Path(pdf_path).stat().st_size)
        info["created_at"] = datetime.now().isoformat()
        info["model"] = "Llama 3.2 3B" #change later
        save_session_info(session_id, info)

        socketio.emit('pipeline-ready', {
            'sessionId': session_id,
            'message': 'PDF processed.'
        })
        
    except Exception as e:
        socketio.emit('pipeline-error', {'error': str(e)})

@socketio.on('ask-question')
def ask_question(data):
    query = data.get('query', "")
    session_id = data.get('session_id', "")
    print("otázka",query, "session_id", session_id)

    if not query or not session_id:
        return

    #process question and send answer
    if not session_id in rag_pipelines:
        #create new rag_pipeline

        #get session folder
        session_path = Path(SESSION_FOLDER) / session_id

        if session_path.exists():
            rag_p = RAG_pipeline(
                chroma_db_path=str(session_path / "chroma_db"),
                llm=llm,
                embedder=embedder,
                socketio=socketio
            )

            #load collection from chromadb
            rag_p.load_collection()

            #save to loaded pipelines
            rag_pipelines[session_id] = rag_p
        else:
            print("Error: Non-existing session.")


    rag_p = rag_pipelines[session_id]
    result = rag_p.ask_context(query)
    add_message(session_id, "user", query) #add my message to chat_history

    if result and not result["streamed"]:
        print("result", result)
        add_message(session_id, "assistant", result["answer"], result["sources"])
        socketio.emit('ask-answer', result)


@socketio.on('start-upload')
def handle_start_upload(data):
    """
        Initialize uploading.
    """
    file_name = data['fileName']
    file_size = data['fileSize']
    session_id = data.get("session_id", "")

    if session_id:
        session_path = Path(f"./sessions/{session_id}")

        #remove old reference
        old_rag = rag_pipelines.get(session_id)

        if old_rag:
            try:
                #try to delete collection
                old_rag.collection.delete()
            except:
                pass

            #close client
            try:
                old_rag.chroma_client.close()
            except:
                pass

            old_rag.collection = None
            old_rag.chroma_client = None #close db connection
            rag_pipelines[session_id] = None

        #run garbage collector
        gc.collect()
        time.sleep(1)

    session_id = str(uuid.uuid4()) #create unique session id for user

    #check size limit
    if file_size > MAX_FILE_SIZE:
        socketio.emit('upload-error', {
            'error': f'File is too big. Max {MAX_FILE_SIZE / (1024 * 1024):.0f} MB'
        })
        return

    file_id = f"{file_name}_{request.sid}"

    #init
    uploads[file_id] = {
        'name': file_name,
        'size': file_size,
        'chunks': {},
        'total_chunks': -1,
        'received': 0,
        'session_id': session_id
    }

    print(f'Upload start: {file_name} ({file_size} bytes)')
    socketio.emit('upload-started', {
        'fileName': file_name,
        'fileId': file_id,
        'sessionId': session_id
    })


@socketio.on('upload-chunk')
def handle_upload_chunk(data):
    """
        Receiving a chunk.
    """
    try:
        file_id = data['fileId']
        chunk_index = data['chunkIndex']
        total_chunks = data['totalChunks']
        is_last = data['isLast']

        #check if file exists
        if file_id not in uploads:
            socketio.emit('upload-error', {'error': 'Uploading was not initialized'})
            return

        #save chunk
        chunk_data = base64.b64decode(data['chunk'])
        uploads[file_id]['chunks'][chunk_index] = chunk_data
        uploads[file_id]['received'] += len(chunk_data)
        uploads[file_id]['total_chunks'] = total_chunks

        #track progress
        progress = (uploads[file_id]['received'] / uploads[file_id]['size']) * 100
        progress = min(100, progress)

        socketio.emit('chunk-received', {
            'chunkIndex': chunk_index,
            'totalChunks': total_chunks,
            'progress': round(progress, 1)
        })

        #if it is the last chunk, merge file
        if is_last:
            print(f'Last chunk received, merging.')
            complete_upload(file_id)

    except Exception as e:
        print(f'Error while receiving chunk: {e}')
        socketio.emit('upload-error', {'error': str(e)})


def complete_upload(file_id):
    """
        Merging all chunks into a single file.
    """
    try:
        upload_data = uploads.get(file_id)
        if not upload_data:
            return

        session_id = upload_data['session_id']
        total_chunks = upload_data['total_chunks']
        chunks = upload_data['chunks']

        #check if any chunk is missing
        missing = []
        for i in range(total_chunks):
            if i not in chunks:
                missing.append(i)

        if missing:
            socketio.emit('upload-error', {
                'error': f'Missing chunks: {missing}'
            })
            return

        #merge
        file_bytes = b''.join([chunks[i] for i in range(total_chunks)])

        #save file
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{upload_data['name']}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)

        with open(filepath, 'wb') as f:
            f.write(file_bytes)

        print(f'File saved: {filepath} ({len(file_bytes)} bytes)')

        #save to session info
        info = load_session_info(session_id) or {"session_id": session_id}
        info["original_filename"] = upload_data['name'] #original name
        save_session_info(session_id, info)

        #send confirmation
        socketio.emit('upload-complete', {
            'fileName': upload_data['name'],
            'filePath': filepath,
            'size': len(file_bytes),
        })

        threading.Thread(target=run_rag_pipeline, args=(session_id, filepath)).start()

        #clear memory
        del uploads[file_id]

    except Exception as e:
        print(f'Error while merging: {e}')
        socketio.emit('upload-error', {'error': str(e)})
        if file_id in uploads:
            del uploads[file_id]


@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected:', request.sid)

if __name__ == '__main__':
    #load HF token
    load_dotenv()
    HF_TOKEN = os.getenv("HF_TOKEN")

    threading.Thread(target=load_models_background, daemon=True).start()
    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)
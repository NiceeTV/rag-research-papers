import base64
import time
import os
from datetime import datetime

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
socketio = SocketIO(app,
                    cors_allowed_origins="*",
                    ping_timeout=3600,
                    max_http_buffer_size=50 * 1024 * 1024, #50 MB buffer
                    ping_interval=25
                    )


UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@socketio.on('connect')
def handle_connect():
    print('Client connected:', request.sid)
    socketio.emit('connected', {'message': 'Connected to server'})

@app.route('/')
def index():
    return render_template('index.html') #main page

uploads = {}

#upload limits
MAX_FILE_SIZE = 50 * 1024 * 1024 #50 MB
CHUNK_SIZE = 512 * 1024 #512 KB chunks

@socketio.on('start-upload')
def handle_start_upload(data):
    """
        Initialize uploading.
    """
    file_name = data['fileName']
    file_size = data['fileSize']

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
        'received': 0
    }

    print(f'Upload start: {file_name} ({file_size} bytes)')
    socketio.emit('upload-started', {
        'fileName': file_name,
        'fileId': file_id
    })


@socketio.on('upload-chunk')
def handle_upload_chunk(data):
    """
        Receiveing a chunk.
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

        #send confirmation
        socketio.emit('upload-complete', {
            'fileName': upload_data['name'],
            'filePath': filepath,
            'size': len(file_bytes),
        })

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
    socketio.run(app, host="0.0.0.0", port=5000, use_reloader=True, allow_unsafe_werkzeug=True)
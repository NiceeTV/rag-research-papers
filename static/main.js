/* CONSTANTS */
const file_input = document.getElementById("file_input");
const upload_btn = document.getElementById("upload_btn");
const progress_cont = document.getElementById("progress_container");
const processed_file = document.getElementById("processed_file");
const progress_perc = document.getElementById("progress_perc");
const progress_ws = document.getElementById("progress_ws");
const progress_bar = document.getElementById("progress_bar");
const fileInfo = document.getElementById('fileInfo');

const chat = document.getElementById("chat");
const socket = io({
                maxHttpBufferSize: 50 * 1024 * 1024,
                transports: ['websocket', 'polling'],
                timeout: 120000
            });

const MAX_FILE_SIZE = 50 * 1024 * 1024; /* 50 MB file limit */
const CHUNK_SIZE = 512 * 1024; /* 512 KB per chunk */
let is_uploading = false;
let current_file_id = null;


/* FUNCTIONS */
function upload() {
    file_input.click();
    
    setTimeout(() => {
        upload_btn.style.display = 'none';
    }, 300);
}

function upload_file(file) {
    /* reset progress bar */
    is_uploading = true;
    upload_btn.disabled = true;
    progress_cont.className = 'visible';
    progress_bar.style.width = '0%';
    progress_perc.textContent = '0%';
    progress_ws.textContent = 'Initialization...';

    /* init the upload */
    socket.emit('start-upload', {
        fileName: file.name,
        fileSize: file.size
    });

    /* wait for confirmation, then start sending chunks */
    socket.once('upload-started', () => {
        send_chunks(file);
    });

    /* if no confirmation */
    setTimeout(() => {
        if (is_uploading && !current_file_id) {
            statusText.textContent = 'Server is not responding.';
        }
    }, 5000);
}

function send_chunks(file) {
    const total_chunks = Math.ceil(file.size / CHUNK_SIZE);
    let offset = 0;
    let chunk_index = 0;

    function send_next_chunk() {
        if (offset >= file.size || !is_uploading) {
            return;
        }

        const chunk = file.slice(offset, offset + CHUNK_SIZE);
        const reader = new FileReader();

        reader.onload = function(event) {
            try {
                const array_buffer = event.target.result;
                const base64_chunk = btoa(
                    new Uint8Array(array_buffer).reduce(
                        (data, byte) => data + String.fromCharCode(byte), ''
                    )
                );

                const is_last = offset + CHUNK_SIZE >= file.size;

                socket.emit('upload-chunk', {
                    fileId: current_file_id,
                    chunk: base64_chunk,
                    chunkIndex: chunk_index,
                    totalChunks: total_chunks,
                    isLast: is_last
                });

                offset += CHUNK_SIZE;
                chunk_index++;

                /* send next chunk */
                setTimeout(send_next_chunk, 10);

            } catch (error) {
                console.error('Error while sending next chunk:', error);
                socket.emit('upload-error', { error: error.message });
            }
        };

        reader.onerror = function(error) {
            console.error('Error while reading file:', error);
            socket.emit('upload-error', { error: 'Error while reading file' });
        };

        reader.readAsArrayBuffer(chunk);
    }

    send_next_chunk();
}

/* validate and process file */
function handle_file(file) {
    /* if already uploading, dont send another file */
    if (is_uploading) {
        showInfo('error', 'Error: Upload already in progress, please wait...');
        return;
    }

    /* check file type */
    if (file.type !== 'application/pdf') {
        showInfo('error', 'Error: PDF files only.');
        file_input.value = '';
        return;
    }

    /* check file size */
    if (file.size > MAX_FILE_SIZE) {
        const sizeMB = (file.size / 1024 / 1024).toFixed(1);
        const maxMB = (MAX_FILE_SIZE / 1024 / 1024);
        showInfo('error', `Error: File has ${sizeMB} MB, limit is ${maxMB} MB`);
        file_input.value = '';
        return;
    }

    /* everything is ok */
    const sizeMB = (file.size / 1024 / 1024).toFixed(1);
    //showInfo('success', `📎 ${file.name} (${sizeMB} MB) - ready for upload`);
    processed_file.textContent = `${file.name} (${sizeMB} MB)`;
    
    /* start upload */
    upload_file(file);
}

function showInfo(type, message) {
    progress_ws.textContent = message;
}


/* EVENTS */
file_input.addEventListener("change",e => {
    const file = e.target.files[0];
    if (file) handle_file(file);
})

/* sockets */
socket.on('connect', () => {
    console.log('Connected to server');
});

socket.on('connected', (data) => {
    console.log('Message from server:', data.message);
});

socket.on('upload-started', (data) => {
    console.log('Upload started:', data.fileName);
    current_file_id = data.fileId;
    progress_ws.textContent = 'Uploading';
});

socket.on('chunk-received', (data) => {
    const progress = data.progress;
    progress_bar.style.width = progress + '%';
    progress_perc.textContent = Math.round(progress) + '%';
    
    if (progress < 100) {
        progress_perc.textContent = `${Math.round(progress)}%`;
    }
});

socket.on('upload-complete', (data) => {
    console.log('File uploaded successfully:', data.fileName);
    progress_bar.style.width = '100%';
    
    showInfo('success', 'Upload finished.');
    
    is_uploading = false;
    upload_btn.disabled = false;
    file_input.value = '';

    /* show chat if upload success */
    chat.className = 'visible'; 
});

socket.on('upload-error', (data) => {
    console.error('Error:', data.error);
    progress_ws.textContent = 'Error!';
    progress_bar.style.background = '#f44336';
    alert('Error while uploading file: ' + data.error);
});

socket.on('disconnect', () => {
    console.log('Disconnected from server.');
});
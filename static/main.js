/* CONSTANTS */
const file_input = document.getElementById("file_input");
const upload_btn = document.getElementById("upload_btn");
const new_chat_btn = document.getElementById("new_chat");
const download_btn = document.getElementById("download_chat");
const progress_cont = document.getElementById("progress_container");
const processed_file = document.getElementById("processed_file");
const progress_perc = document.getElementById("progress_perc");
const progress_ws = document.getElementById("progress_ws");
const progress_bar = document.getElementById("progress_bar");
const fileInfo = document.getElementById('fileInfo');
const send_msg_btn = document.getElementById("message_send_btn");
const msg_area = document.getElementById("message_area");
const msg_cont = document.getElementById("msg_container");
const chat = document.getElementById("chat");
const sidebar = document.getElementById("sidebar");

let s_id = sessionStorage.getItem("session_id");
const socket = io({
                maxHttpBufferSize: 50 * 1024 * 1024, /* max size of socket message, 50MB*/
                transports: ['websocket', 'polling'],
                timeout: 120000
            });

const MAX_FILE_SIZE = 50 * 1024 * 1024; /* 50 MB file limit */
const CHUNK_SIZE = 512 * 1024; /* 512 KB per chunk */
let is_uploading = false;
let current_file_id = null;
const session_cache = {};
let active_session_btn = null;
let models_ready = null;

/* FUNCTIONS */
function upload_file(file) {
    /* reset progress bar */
    is_uploading = true;
    upload_btn.disabled = true;
    progress_cont.className = 'visible';
    progress_bar.style.width = '0%';
    progress_perc.textContent = '0%';
    progress_ws.textContent = 'Initialization...';

    /** UI reset **/
    /* hide chat and reset chat_history */
    if (chat && chat.classList.contains('visible')) {
        chat.classList.remove('visible');
    }
    sessionStorage.setItem('chat_history','');
    if (msg_cont) {
        msg_cont.innerHTML = '';
    }
    /** UI reset end **/

    /* init the upload */
    socket.emit('start-upload', {
        fileName: file.name,
        fileSize: file.size,
        session_id: s_id,
    });

    /* wait for confirmation, then start sending chunks */
    socket.once('upload-started', () => {
        send_chunks(file);
    });

    /* if no confirmation */
    setTimeout(() => {
        if (is_uploading && !current_file_id) {
            progress_ws.textContent = 'Server is not responding.';
        }
    }, 5000);
}

/* send chunks */
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
    processed_file.textContent = `${file.name} (${sizeMB} MB)`;
    processed_file.title = `${file.name} (${sizeMB} MB)`;
    
    /* start upload */
    upload_file(file);
}

/* change progress message */
function showInfo(type, message) {
    progress_ws.textContent = message;
}

/* draw message to msg_container */
function send_msg_to_cont(message="", role="user", srcs="") {
    if (role !== "user" && role !== "assistant") {
        return;
    }

    const el = document.createElement("div");
    el.className = `message ${role}`;
    el.textContent = message;

    if (role === "assistant") {
        /* add sources to the answer */
        el.title = `Sources: ${srcs}`;
    }

    /* add to container */
    msg_cont.appendChild(el);
    return el;
}

/* save and load chats on refresh */
function save_chat() {
    const messages = [];
    msg_cont.querySelectorAll('.message').forEach(el => {
        messages.push({
            text: el.textContent.trim(),
            role: el.classList.contains('user') ? 'user' : 'assistant',
            sources: el.getAttribute('title') || ''
        });
    });

    console.log('messages saved',messages);

    /* save to local storage */
    sessionStorage.setItem('chat_history', JSON.stringify(messages));
}

/* load session info */
function load_session(session_id) {
    if (session_id in session_cache) {
        const session_data = session_cache[session_id];
        load_session_from_data(session_data);
        console.log(`CACHE: Loading ${session_id} from cache.`)
    }
    else {
        socket.emit('load-session', { session_id: session_id });
    }
}

/* load UI data from session data */
function load_session_from_data(data) {
    console.log('data load',data);
    const session_id = data.session_id;
    if (session_id) {
        session_cache[session_id] = data;
    }

    /* load ui */
    /* load progress and file info */
    if (processed_file) {
        processed_file.textContent = data.file_name;
        processed_file.title = data.file_name;
    }

    /* show upload and chat container */
    progress_cont.className = "";
    chat.className = "visible";
    
    const messages = data.messages;
    msg_cont.innerHTML = ''; /* clear container */
    
    messages.forEach(msg => {
        send_msg_to_cont(msg.text, msg.role, msg.sources);
    });

    /* hide upload_btn */
    upload_btn.style.display = 'none';

    console.log('Loading session:',data.session_id);
}


/* EVENTS */
file_input.addEventListener("change",e => {
    const file = e.target.files[0];
    if (file) handle_file(file);
});

/* upload file to backend */
upload_btn.addEventListener("click", (e)=> {
    file_input.click();
    
    setTimeout(() => {
        e.target.style.display = 'none';
    }, 300);
});

/* upload another file */
new_chat_btn.addEventListener("click", (e)=> {
    file_input.click();
});

/* export chat to markdown */
download_btn.addEventListener("click", (e)=> {
    /* get chat info and messages from sessionStorage */
    const filename = sessionStorage.getItem("file_info") || 'unknown';
    const now = new Date().toLocaleString();
    const sessionId = sessionStorage.getItem("session_id") || 'unknown';
    const model = 'Llama 3.2 3B'; /* todo: to change */
    const chat_history = sessionStorage.getItem("chat_history") || '[]';
    const messages = JSON.parse(chat_history);  

    /* create markdown */
    let markdown = `# Chat export: ${filename}\n\n`;
    markdown += `**Date:** ${now}\n\n`;
    markdown += `**Session ID:** ${sessionId}\n\n`;
    markdown += `**Model:** ${model}\n\n`;
    markdown += `**Number of messages:** ${messages.length}\n\n---\n\n`;

    messages.forEach(msg => {
        markdown += `## ${msg.role}\n`;
        if (msg.sources) markdown += `*(${msg.sources})*\n`;
        markdown += `${msg.text}\n\n`;
    });

    markdown += `\n---\n*Export generated ${new Date().toLocaleString()}*`;

    /* download the export */
    const blob = new Blob([markdown], {type: 'text/markdown'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chat_${filename.replace('.pdf', '')}_${new Date().toISOString().slice(0,10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
});


/* send message with button */
send_msg_btn.addEventListener("click", ()=> {
    if (!models_ready) return;
    const message = msg_area.value;
    send_msg_to_cont(message);

    /* ask backend for answer */
    socket.emit('ask-question', {
        "query": message,
        "session_id": s_id
    });

    /* clear input */
    msg_area.value = '';
    save_chat(); 
});

/* send message with Enter while on textarea */
msg_area.addEventListener('keydown', function(event) {
    if (!models_ready) return;
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault(); /* dont make newline */
        
        const message = msg_area.value;
        send_msg_to_cont(message);

        /* ask backend for answer */
        socket.emit('ask-question', {
            "query": message,
            "session_id": s_id
        });

        /* clear input */
        msg_area.value = '';
        save_chat(); 
    }
});

sidebar.addEventListener('click', e => {
    const target = e.target;
    if (target.classList.contains('sidebar_chat')) {
        const session_id = target.dataset.session_id;
        if (session_id) {
            load_session(session_id);
        }

        /* remove old active session btn */
        if (active_session_btn) {
            active_session_btn.classList.remove('active');
        }

        /* select as active session */
        active_session_btn = target;
        target.classList.add('active');
    }
})

/* sockets */
socket.on('connect', () => {
    if (s_id) {
        console.log('haloo',s_id);
        load_session(s_id);
    }

    console.log('Connected to server');
});

/* on opening the site/refreshing */
socket.on('connected', (data) => {
    console.log('Message from server:', data.message);
    const model_state = data.models_ready;
    console.log('model state', model_state);

    models_ready = model_state;
    if (model_state === false) {
        upload_btn.disabled = true;
        upload_btn.title = "Models are not ready yet. Please wait.";

        /* disable chat sending*/
        msg_area.disabled = true;
        msg_area.title = "Models are not ready yet. Please wait.";

        /* disable send button */
        send_msg_btn.disabled = true;
        send_msg_btn.title = "Models are not ready yet. Please wait.";
    }

    /* sessions list */
    const session_list = data.sessions;
    console.log('sessions', session_list);
    if (session_list && session_list.length > 0) {
        if (session_list && sidebar) {
            /* clear sidebar */
            sidebar.querySelectorAll('.sidebar_chat').forEach(el => el.remove());

            session_list.forEach(s => {
                /* add session to list */
                const chat_div = document.createElement("div");
                chat_div.className = "sidebar_chat";
                chat_div.title = s.file_name;
                chat_div.dataset.session_id = s.session_id;

                const chat_span = document.createElement("span");
                chat_span.className = "sidebar_chat_text";
                chat_span.textContent = s.file_name;

                chat_div.appendChild(chat_span);
                sidebar.appendChild(chat_div);
            })

            /* set most recent as active */
            const most_recent = sidebar.children[1]; /* 0 is toolbar */
            if (most_recent) {
                if (active_session_btn) {
                    active_session_btn.classList.remove('active');
                }

                most_recent.classList.add('active');
                active_session_btn = most_recent;
            }
            else {
                /* no sessions, show upload btn */
                upload_btn.style.display = 'block';
            }
        }
    }
});


/* load user session */
socket.on('session-loaded', (data) => {
    load_session_from_data(data);
});


/* backend confirmed our upload init, receive session_id */
socket.on('upload-started', (data) => {
    console.log('Upload started:', data.fileName);
    current_file_id = data.fileId;
    progress_ws.textContent = 'Uploading';

    /* receive session id */
    s_id = data.sessionId;
    console.log('nove s_id',s_id);

    sessionStorage.setItem('chat_history', '');
    sessionStorage.setItem('session_id', s_id);
});

/* backend received our chunk, update progress */
socket.on('chunk-received', (data) => {
    const progress = data.progress;
    progress_bar.style.width = progress + '%';
    progress_perc.textContent = Math.round(progress) + '%';
    
    if (progress < 100) {
        progress_perc.textContent = `${Math.round(progress)}%`;
    }
});

/* upload success */
socket.on('upload-complete', (data) => {
    console.log('File uploaded successfully:', data.fileName);
    progress_bar.style.width = '100%';
    
    showInfo('success', 'Upload finished.');
    
    is_uploading = false;
    upload_btn.disabled = false;
    file_input.value = '';

    /* pipeline has started */
    progress_ws.textContent = 'Processing has started';
    progress_perc.textContent = '0%';
});

/* error while uploading */
socket.on('upload-error', (data) => {
    console.error('Error:', data.error);
    progress_ws.textContent = 'Error!';
    progress_bar.style.background = '#f44336';
    alert('Error while uploading file: ' + data.error);
});

/* pipeline progress */
socket.on('pipeline-status', (data) => {
    console.log('Pipeline status update:',data.state);
    progress_ws.textContent = data.state;
    const pipeline_part = data.part;

    /* step of the pipeline */
    if (pipeline_part && pipeline_part > 0) {
        progress_perc.textContent = `${Math.round(pipeline_part*(100/3))}%`; /* 3 steps: ingest, chunk, embed */
        progress_bar.style.width = `${Math.round(pipeline_part*(100/3))}%`;
    }

    /* show state if processing finished */
    if (data.state === "Finished") {
        progress_ws.textContent = "Processing finished.";
        progress_perc.textContent = '100%';
        progress_bar.style.width = '100%';
        chat.className = "visible";

        /* save ui text to sessionStorage */
        sessionStorage.setItem("file_info", processed_file.textContent);
        sessionStorage.setItem("progress_perc", parseInt(progress_perc.textContent.replace('%', '')));
        sessionStorage.setItem("progress_ws", progress_ws.textContent);
    }
});

/* receive answer to our question */
socket.on('ask-answer', (data) => {
    send_msg_to_cont(data.answer, "assistant", data.sources);
    save_chat(); 
});

/* answer streaming */
let answer_stream = null;

socket.on('answer-start', (data) => {
    answer_stream = send_msg_to_cont("", "assistant", data.sources);
});

socket.on('answer-token', (data) => {
    if (answer_stream) {
        answer_stream.textContent += data.token;
    }
});

socket.on('answer-done', (data) => {
    answer_stream = null;
    save_chat(); 
});



/* when models are loaded, signal will come */
socket.on('model-ready', (data) => {
    upload_btn.disabled = false;
    msg_area.disabled = false;
    send_msg_btn.disabled = false;
    models_ready = true;

    upload_btn.style.backgroundColor = '#a6a6a6';
    msg_area.style.backgroundColor = '#a6a6a6';
    send_msg_btn.style.backgroundColor = '#a6a6a6';

    setTimeout(() => {
        upload_btn.style.backgroundColor = '';
        upload_btn.title = '';

        msg_area.style.backgroundColor = '';
        msg_area.title = '';

        send_msg_btn.style.backgroundColor = '';
        send_msg_btn.title = '';
    }, 1000);

});

/* user closes tab or closes browser */
socket.on('disconnect', () => {
    console.log('Disconnected from server.');
});
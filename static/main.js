const file_input = document.getElementById("file_input");
console.log('input',file_input);

function upload() {
    file_input.click();
}

file_input.addEventListener("change",e => {
    const file = e.target.files[0];


    console.log("files uploaded", file.name);

})


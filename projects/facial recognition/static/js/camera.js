class Camera {
  constructor(videoEl, canvasEl) {
    this.video = videoEl;
    this.canvas = canvasEl;
    this.stream = null;
  }

  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
    });
    this.video.srcObject = this.stream;
    await new Promise((res) => (this.video.onloadedmetadata = res));
    this.video.play();
  }

  stop() {
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
  }

  capture() {
    const ctx = this.canvas.getContext("2d");
    this.canvas.width = this.video.videoWidth || 640;
    this.canvas.height = this.video.videoHeight || 480;
    ctx.drawImage(this.video, 0, 0);
    return this.canvas.toDataURL("image/jpeg", 0.92);
  }
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

function showAlert(el, msg, type = "error") {
  el.textContent = msg;
  el.className = `alert ${type} show`;
}

function setBtn(btn, spinner, loading, label) {
  btn.disabled = loading;
  spinner.classList.toggle("show", loading);
  btn.querySelector(".btn-label").textContent = label;
}

'use strict';

let currentClass      = null;
let currentSession    = null;
let facePhotoFile     = null;
let regStream         = null;
let attStream         = null;
let regCapturedBlob   = null;
let autoScanInterval  = null;

const MI   = s => `<span class="material-icons" style="font-size:15px;line-height:1">${s}</span>`;
const ICON = { ok: MI('check_circle'), err: MI('error'), warn: MI('warning'), cam: MI('photo_camera'), close: MI('close'), vid: MI('videocam') };

// ── Helpers ────────────────────────────────────────────────────────────────────
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2200);
}

function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) { window.location.href = '/login'; return {}; }
  return res.json();
}

async function doLogout() {
  await fetch('/api/auth/logout', { method: 'POST' });
  window.location.href = '/login';
}

function showOverlay(msg, hint = '') {
  document.getElementById('overlay-msg').textContent  = msg;
  document.getElementById('overlay-hint').textContent = hint;
  document.getElementById('overlay').style.display = 'flex';
}
function hideOverlay() { document.getElementById('overlay').style.display = 'none'; }

function showPage(name) {
  if (name !== 'registry')   { stopStream(regStream); regStream = null; }
  if (name !== 'attendance') closeLiveCam();
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  document.querySelectorAll('nav a').forEach(a => a.classList.remove('active'));
  const nav = document.getElementById('nav-' + name);
  if (nav) nav.classList.add('active');
  if (name === 'registry') loadRegistry();
  if (name === 'classes')  loadClasses();
}


// ── ═══════════ WEBCAM UTILITIES ═══════════ ──────────────────────────────────

async function startCamera(videoEl) {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } },
    });
    videoEl.srcObject = stream;
    return stream;
  } catch {
    toast('Camera access denied or unavailable');
    return null;
  }
}

function stopStream(stream) {
  if (stream) stream.getTracks().forEach(t => t.stop());
}

function captureFrame(videoEl) {
  return new Promise(resolve => {
    const canvas = document.createElement('canvas');
    canvas.width  = videoEl.videoWidth  || 640;
    canvas.height = videoEl.videoHeight || 480;
    canvas.getContext('2d').drawImage(videoEl, 0, 0);
    canvas.toBlob(blob => resolve(blob), 'image/jpeg', 0.92);
  });
}


// ── ═══════════ STUDENT REGISTRY ═══════════ ──────────────────────────────────

function previewRegPhoto(input) {
  const file = input.files[0];
  if (!file) return;
  const img = document.getElementById('reg-thumb');
  const ph  = document.getElementById('reg-thumb-placeholder');
  const reader = new FileReader();
  reader.onload = ev => { img.src = ev.target.result; img.style.display = 'block'; ph.style.display = 'none'; };
  reader.readAsDataURL(file);
}

async function setRegPhotoMode(mode) {
  document.getElementById('reg-upload-mode').style.display  = mode === 'upload' ? '' : 'none';
  document.getElementById('reg-camera-mode').style.display  = mode === 'camera' ? '' : 'none';
  document.getElementById('pmt-upload').classList.toggle('active', mode === 'upload');
  document.getElementById('pmt-camera').classList.toggle('active', mode === 'camera');

  if (mode === 'camera') {
    const video = document.getElementById('reg-video');
    video.style.display = 'block';
    document.getElementById('reg-cam-capture').style.display = 'none';
    document.getElementById('reg-capture-btn').style.display = '';
    document.getElementById('reg-retake-btn').style.display  = 'none';
    regCapturedBlob = null;
    regStream = await startCamera(video);
  } else {
    stopStream(regStream);
    regStream = null;
    regCapturedBlob = null;
  }
}

async function captureRegPhoto() {
  const video   = document.getElementById('reg-video');
  regCapturedBlob = await captureFrame(video);
  stopStream(regStream);
  regStream = null;

  const url     = URL.createObjectURL(regCapturedBlob);
  const capture = document.getElementById('reg-cam-capture');
  capture.src   = url;
  capture.style.display = 'block';
  video.style.display   = 'none';
  document.getElementById('reg-capture-btn').style.display = 'none';
  document.getElementById('reg-retake-btn').style.display  = '';

  // Mirror the thumb preview
  const img = document.getElementById('reg-thumb');
  const ph  = document.getElementById('reg-thumb-placeholder');
  img.src = url; img.style.display = 'block'; ph.style.display = 'none';
}

async function retakeRegPhoto() {
  regCapturedBlob = null;
  const video   = document.getElementById('reg-video');
  const capture = document.getElementById('reg-cam-capture');
  capture.style.display = 'none';
  video.style.display   = 'block';
  document.getElementById('reg-capture-btn').style.display = '';
  document.getElementById('reg-retake-btn').style.display  = 'none';
  regStream = await startCamera(video);
}

async function loadRegistry() {
  const students = await api('GET', '/api/students');
  const tbody = document.getElementById('registry-body');
  if (!students.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">No students registered yet.</td></tr>';
    return;
  }
  tbody.innerHTML = students.map(s => {
    const initial = (s.name || '?')[0].toUpperCase();
    const avatar  = s.photo_path
      ? `<img class="reg-avatar" src="/uploads/${esc(s.photo_path)}" alt="${esc(s.name)}" onerror="this.style.display='none'">`
      : `<span class="reg-avatar-placeholder">${initial}</span>`;
    return `<tr>
      <td style="width:36px">${avatar}</td>
      <td><span class="badge badge-blue" style="font-family:monospace;letter-spacing:0.05em">${esc(s.index_number)}</span></td>
      <td><strong>${esc(s.name)}</strong></td>
      <td style="color:var(--muted);font-size:12px">${s.enrolled_at ? s.enrolled_at.split(' ')[0] : ''}</td>
      <td><button class="btn btn-danger btn-sm" onclick="deleteStudent(${s.id})">Remove</button></td>
    </tr>`;
  }).join('');
}

async function registerStudent() {
  const index_number = document.getElementById('reg-index').value.trim();
  const name         = document.getElementById('reg-name').value.trim();
  const fb           = document.getElementById('reg-feedback');

  if (!index_number || !name) { toast('Fill in both index number and name'); return; }

  const isCamMode = document.getElementById('reg-camera-mode').style.display !== 'none';
  let photo;

  if (isCamMode) {
    if (!regCapturedBlob) { toast('Please capture a photo first'); return; }
    photo = regCapturedBlob;
  } else {
    const photoInput = document.getElementById('reg-photo');
    photo = photoInput.files[0];
    if (!photo) { toast('Please choose a face photo'); return; }
  }

  const fd = new FormData();
  fd.append('name', name);
  fd.append('index_number', index_number);
  fd.append('photo', photo, isCamMode ? 'capture.jpg' : photo.name);

  showOverlay('Detecting face…', 'Extracting facial embedding');
  try {
    const res  = await fetch('/api/students/enroll', { method: 'POST', body: fd });
    const data = await res.json();
    hideOverlay();
    if (!res.ok) {
      fb.innerHTML = `<span class="feedback-err">${ICON.err} ${esc(data.error)}</span>`;
      return;
    }
    document.getElementById('reg-index').value = '';
    document.getElementById('reg-name').value  = '';

    if (isCamMode) {
      regCapturedBlob = null;
      const video   = document.getElementById('reg-video');
      const capture = document.getElementById('reg-cam-capture');
      capture.style.display = 'none';
      video.style.display   = 'block';
      document.getElementById('reg-capture-btn').style.display = '';
      document.getElementById('reg-retake-btn').style.display  = 'none';
      regStream = await startCamera(video);
    } else {
      document.getElementById('reg-photo').value = '';
      document.getElementById('reg-thumb').style.display = 'none';
      document.getElementById('reg-thumb-placeholder').style.display = '';
    }

    fb.innerHTML = `<span class="feedback-ok">${ICON.ok} ${esc(name)} registered</span>`;
    setTimeout(() => { fb.innerHTML = ''; }, 3000);
    loadRegistry();
    toast(`${name} registered`);
  } catch {
    hideOverlay();
    fb.innerHTML = `<span class="feedback-err">${ICON.err} Network error — is the server running?</span>`;
  }
}

async function deleteStudent(id) {
  if (!confirm('Remove this student from the registry? This also removes their attendance records.')) return;
  await api('DELETE', `/api/students/${id}`);
  loadRegistry();
  toast('Student removed');
}


// ── ═══════════ CLASSES ═══════════ ───────────────────────────────────────────

async function loadClasses() {
  const classes = await api('GET', '/api/classes');
  const el = document.getElementById('classes-list');
  if (!classes.length) {
    el.innerHTML = '<div class="empty" style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius)">No classes yet.</div>';
    return;
  }
  el.innerHTML = classes.map(c => `
    <div class="session-card" style="cursor:pointer" onclick="openClass(${c.id}, '${esc(c.name)}')">
      <div>
        <strong>${esc(c.name)}</strong>
        <div style="font-size:12px;color:var(--muted)">${esc(c.description || '')}</div>
      </div>
      <div class="row">
        <button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();openClass(${c.id},'${esc(c.name)}')">Open &rarr;</button>
        <button class="btn btn-danger btn-sm" onclick="event.stopPropagation();deleteClass(${c.id})">Delete</button>
      </div>
    </div>
  `).join('');
}

async function createClass() {
  const name        = document.getElementById('new-class-name').value.trim();
  const description = document.getElementById('new-class-desc').value.trim();
  if (!name) return toast('Enter a class name');
  const res = await api('POST', '/api/classes', { name, description });
  if (res.error) return toast(res.error);
  document.getElementById('new-class-name').value = '';
  document.getElementById('new-class-desc').value = '';
  loadClasses();
  toast('Class created');
}

async function deleteClass(id) {
  if (!confirm('Delete this class and all its data?')) return;
  await api('DELETE', `/api/classes/${id}`);
  loadClasses();
  toast('Class deleted');
}

function openClass(id, name) {
  currentClass = { id, name };
  document.getElementById('class-heading').textContent = name;
  showPage('class');
  switchTab('enroll');
}


// ── ═══════════ CLASS TABS ═══════════ ────────────────────────────────────────

function switchTab(tab) {
  document.querySelectorAll('.tab').forEach((t, i) => {
    t.classList.toggle('active', ['enroll','sessions','analytics'][i] === tab);
  });
  document.getElementById('tab-enroll').style.display   = tab === 'enroll'   ? '' : 'none';
  document.getElementById('tab-sessions').style.display  = tab === 'sessions'  ? '' : 'none';
  document.getElementById('tab-analytics').style.display = tab === 'analytics' ? '' : 'none';
  if (tab === 'enroll')    loadEnroll();
  if (tab === 'sessions')  loadSessions();
  if (tab === 'analytics') loadAnalytics();
}

// ── Enroll tab ─────────────────────────────────────────────────────────────────

async function loadEnroll() {
  const [all, enrolled] = await Promise.all([
    api('GET', '/api/students'),
    api('GET', `/api/classes/${currentClass.id}/students`),
  ]);
  const enrolledIds = new Set(enrolled.map(s => s.id));
  const notEnrolled = all.filter(s => !enrolledIds.has(s.id));
  const el = document.getElementById('tab-enroll');
  el.innerHTML = `
    <div class="card">
      <div class="card-title">Enroll a Student</div>
      ${notEnrolled.length ? `
        <div class="row">
          <select id="enroll-select" style="flex:1;max-width:340px">
            ${notEnrolled.map(s => `<option value="${s.id}">${esc(s.index_number)} — ${esc(s.name)}</option>`).join('')}
          </select>
          <button class="btn btn-primary" onclick="enrollStudent()">Enroll</button>
          <button class="btn btn-ghost"   onclick="enrollAll()">Enroll All (${notEnrolled.length})</button>
        </div>
      ` : `<p style="color:var(--muted);font-size:13px">All registered students are already enrolled, or no students in registry.</p>`}
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th></th><th>Index No.</th><th>Name</th><th></th></tr></thead>
        <tbody>
          ${enrolled.length ? enrolled.map(s => {
            const initial = (s.name || '?')[0].toUpperCase();
            const avatar  = s.photo_path
              ? `<img class="reg-avatar" src="/uploads/${esc(s.photo_path)}" alt="${esc(s.name)}" onerror="this.style.display='none'">`
              : `<span class="reg-avatar-placeholder">${initial}</span>`;
            return `<tr>
              <td style="width:36px">${avatar}</td>
              <td><span class="badge badge-blue" style="font-family:monospace">${esc(s.index_number)}</span></td>
              <td>${esc(s.name)}</td>
              <td><button class="btn btn-ghost btn-sm" onclick="unenroll(${s.id})">Remove</button></td>
            </tr>`;
          }).join('') : '<tr><td colspan="4" class="empty">No students enrolled yet.</td></tr>'}
        </tbody>
      </table>
    </div>`;
}

async function enrollStudent() {
  const student_id = document.getElementById('enroll-select').value;
  const res = await api('POST', `/api/classes/${currentClass.id}/students`, { student_id: parseInt(student_id) });
  if (res.error) return toast(res.error);
  loadEnroll();
  toast('Student enrolled');
}

async function enrollAll() {
  const [all, enrolled] = await Promise.all([
    api('GET', '/api/students'),
    api('GET', `/api/classes/${currentClass.id}/students`),
  ]);
  const enrolledIds = new Set(enrolled.map(s => s.id));
  const notEnrolled = all.filter(s => !enrolledIds.has(s.id));
  if (!notEnrolled.length) return toast('All students already enrolled');
  await Promise.all(notEnrolled.map(s =>
    api('POST', `/api/classes/${currentClass.id}/students`, { student_id: s.id })
  ));
  loadEnroll();
  toast(`${notEnrolled.length} student${notEnrolled.length > 1 ? 's' : ''} enrolled`);
}

async function unenroll(studentId) {
  await api('DELETE', `/api/classes/${currentClass.id}/students/${studentId}`);
  loadEnroll();
  toast('Student removed from class');
}


// ── Sessions tab ───────────────────────────────────────────────────────────────

async function loadSessions() {
  const sessions = await api('GET', `/api/classes/${currentClass.id}/sessions`);
  const el = document.getElementById('tab-sessions');
  el.innerHTML = `
    <div class="card">
      <div class="card-title">Create Session</div>
      <div class="grid2">
        <div class="field">
          <label>Title</label>
          <input type="text" id="sess-title" placeholder="e.g. Week 3 Lecture" />
        </div>
        <div class="field">
          <label>Date</label>
          <input type="date" id="sess-date" value="${new Date().toISOString().split('T')[0]}" />
        </div>
      </div>
      <div class="field" style="max-width:200px">
        <label>Weight <span class="field-note">(1 = normal, 2 = exam)</span></label>
        <input type="number" id="sess-weight" value="1" min="0.1" max="10" step="0.1" />
      </div>
      <button class="btn btn-primary" onclick="createSession()">Create Session</button>
    </div>
    ${sessions.length ? sessions.map(s => `
      <div class="session-card" id="sess-card-${s.id}">
        <div>
          <strong>${esc(s.title)}</strong>
          ${s.weight != 1 ? `<span class="weight-tag">&times;${s.weight}</span>` : ''}
          <div style="font-size:12px;color:var(--muted)">${s.date} &nbsp;&middot;&nbsp; <span class="badge badge-green">${s.present_count} present</span></div>
        </div>
        <div class="row">
          <button class="btn btn-primary btn-sm" onclick="openAttendance(${s.id},'${esc(s.title)}','${s.date}')">Take Attendance</button>
          <button class="btn btn-ghost btn-sm"   onclick="editSession(${s.id},'${esc(s.title)}','${s.date}',${s.weight})">Edit</button>
          <button class="btn btn-danger btn-sm"  onclick="deleteSession(${s.id})">Delete</button>
        </div>
      </div>
    `).join('') : `<div class="empty" style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius)">No sessions yet.</div>`}`;
}

async function createSession() {
  const title  = document.getElementById('sess-title').value.trim();
  const date   = document.getElementById('sess-date').value;
  const weight = document.getElementById('sess-weight').value;
  if (!title || !date) return toast('Enter title and date');
  const res = await api('POST', `/api/classes/${currentClass.id}/sessions`, { title, date, weight });
  if (res.error) return toast(res.error);
  loadSessions();
  toast('Session created');
}

async function editSession(id, title, date, weight) {
  const newTitle  = prompt('Session title:', title);
  if (newTitle === null) return;
  const newDate   = prompt('Date (YYYY-MM-DD):', date);
  if (newDate === null) return;
  const newWeight = prompt('Weight (e.g. 1, 2):', weight);
  if (newWeight === null) return;
  const res = await api('PUT', `/api/sessions/${id}`, { title: newTitle.trim(), date: newDate.trim(), weight: parseFloat(newWeight) || 1 });
  if (res.error) return toast(res.error);
  loadSessions();
  toast('Session updated');
}

async function deleteSession(id) {
  if (!confirm('Delete session and its attendance records?')) return;
  await api('DELETE', `/api/sessions/${id}`);
  loadSessions();
  toast('Session deleted');
}


// ── Analytics tab ──────────────────────────────────────────────────────────────

async function loadAnalytics() {
  const el = document.getElementById('tab-analytics');
  el.innerHTML = '<div class="empty">Loading…</div>';
  const data = await api('GET', `/api/classes/${currentClass.id}/analytics`);
  if (!data.students?.length) {
    el.innerHTML = '<div class="empty" style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius)">No data yet. Add sessions and take attendance first.</div>';
    return;
  }

  const atRisk = data.students.filter(s => s.flags.length);
  let html = `
    <div style="display:flex;gap:12px;flex-wrap:wrap;padding:10px 14px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:14px;font-size:13px;align-items:center">
      <span style="font-weight:600;color:var(--muted);margin-right:4px">Legend:</span>
      <span style="display:inline-flex;align-items:center;gap:5px"><span class="flag flag-red"><span class="material-icons" style="font-size:15px;vertical-align:middle">trending_down</span></span> Below 50%</span>
      <span style="display:inline-flex;align-items:center;gap:5px"><span class="flag flag-warn"><span class="material-icons" style="font-size:15px;vertical-align:middle">event_busy</span></span> 2+ consecutive absences</span>
    </div>`;

  if (atRisk.length) {
    html += `<div class="card" style="border-color:#fca5a5">
      <div class="card-title" style="color:var(--danger);display:flex;align-items:center;gap:6px"><span class="material-icons" style="font-size:16px">warning</span> At-Risk Students</div>
      ${atRisk.map(s => `
        <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid #f9e2e2">
          <div><strong>${esc(s.student.name)}</strong> <span style="color:var(--muted);font-size:12px;font-family:monospace">${esc(s.student.index_number)}</span></div>
          <div>${s.flags.map(f => `<span class="flag ${f.type === 'low_attendance' ? 'flag-red' : 'flag-warn'}"><span class="material-icons" style="font-size:15px;vertical-align:middle">${f.type === 'low_attendance' ? 'trending_down' : 'event_busy'}</span> ${esc(f.message)}</span>`).join('')}</div>
        </div>`).join('')}
    </div>`;
  }

  html += `<div class="table-wrap">
    <table>
      <thead><tr><th>Student</th><th>Attendance Rate</th><th>Consec. Absences</th><th>Status</th></tr></thead>
      <tbody>
        ${data.students.map(s => {
          const r = s.rate;
          const color = r === null ? '#ccc' : r < 50 ? '#dc2626' : r < 75 ? '#d97706' : '#16a34a';
          return `<tr>
            <td>
              <div><strong>${esc(s.student.name)}</strong></div>
              <div style="font-size:11px;color:var(--muted);font-family:monospace">${esc(s.student.index_number)}</div>
            </td>
            <td>
              <div class="rate-bar">
                <div class="bar"><div class="bar-fill" style="width:${r ?? 0}%;background:${color}"></div></div>
                <span style="font-size:13px;font-weight:600;color:${color}">${r !== null ? r + '%' : '—'}</span>
              </div>
            </td>
            <td style="font-size:13px;${s.currentConsec >= 2 ? 'color:var(--warn);font-weight:600' : ''}">${s.currentConsec}</td>
            <td>${s.flags.length
              ? s.flags.map(f => `<span class="flag ${f.type === 'low_attendance' ? 'flag-red' : 'flag-warn'}"><span class="material-icons" style="font-size:15px;vertical-align:middle">${f.type === 'low_attendance' ? 'trending_down' : 'event_busy'}</span></span>`).join('')
              : `<span style="color:var(--green);font-size:13px;font-weight:600;display:inline-flex;align-items:center;gap:3px"><span class="material-icons" style="font-size:16px">check_circle</span> OK</span>`
            }</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
  </div>`;

  html += `<div class="table-wrap" style="overflow-x:auto">
    <table>
      <thead>
        <tr>
          <th>Student</th>
          ${data.sessions.map(s => `<th style="text-align:center;min-width:80px">
            ${esc(s.title)}${s.weight != 1 ? `<span class="weight-tag">&times;${s.weight}</span>` : ''}
            <div style="font-weight:400;color:var(--muted)">${s.date}</div>
          </th>`).join('')}
        </tr>
      </thead>
      <tbody>
        ${data.students.map(s => `
          <tr>
            <td><strong>${esc(s.student.name)}</strong></td>
            ${s.records.map(r => `
              <td style="text-align:center">
                <span class="badge ${r.status === 'present' ? 'badge-green' : 'badge-red'}">${r.status === 'present' ? 'P' : 'A'}</span>
              </td>`).join('')}
          </tr>`).join('')}
      </tbody>
    </table>
  </div>`;

  el.innerHTML = html;
}


// ── ═══════════ ATTENDANCE PAGE ═══════════ ───────────────────────────────────

function openAttendance(sessionId, title, date) {
  currentSession = { id: sessionId, title, date };
  document.getElementById('att-heading').textContent = `${title} — ${date}`;
  document.getElementById('att-back').onclick = () => { showPage('class'); switchTab('sessions'); };
  document.getElementById('mark-input').value = '';
  document.getElementById('mark-feedback').innerHTML = '';
  closeFaceRec();
  resetFaceRecPanel();
  closeLiveCam();
  showPage('attendance');
  loadAttendance();
  setTimeout(() => document.getElementById('mark-input').focus(), 120);
}

document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && document.getElementById('page-attendance').classList.contains('active')) {
    const active = document.activeElement;
    if (!active?.closest('#face-rec-panel') && !active?.closest('#live-cam-panel')) markStudent();
  }
});

async function loadAttendance() {
  const [records, enrolled] = await Promise.all([
    api('GET', `/api/sessions/${currentSession.id}/attendance`),
    api('GET', `/api/classes/${currentClass.id}/students`),
  ]);
  document.getElementById('att-count').textContent = records.length;
  document.getElementById('att-total-enrolled').textContent = `${enrolled.length} enrolled in this class`;
  const tbody = document.getElementById('att-body');
  if (!records.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">No one marked present yet.</td></tr>';
    return;
  }
  tbody.innerHTML = records.map(r => {
    const time   = r.logged_at ? (r.logged_at.split(' ')[1]?.slice(0,5) ?? r.logged_at) : '';
    const method = r.confidence != null
      ? `<span class="badge badge-blue" title="${r.confidence}% confidence">Face ID</span>`
      : `<span class="badge badge-gray">Manual</span>`;
    return `<tr>
      <td><span class="badge badge-blue" style="font-family:monospace">${esc(r.index_number)}</span></td>
      <td><strong>${esc(r.student_name)}</strong></td>
      <td>${method}</td>
      <td style="color:var(--muted);font-size:12px">${time}</td>
      <td><button class="btn btn-ghost btn-sm" onclick="undoMark(${r.student_id})">Undo</button></td>
    </tr>`;
  }).join('');
}

async function markStudent() {
  const input        = document.getElementById('mark-input');
  const fb           = document.getElementById('mark-feedback');
  const index_number = input.value.trim();
  if (!index_number) return;
  const res = await api('POST', `/api/sessions/${currentSession.id}/mark`, { index_number });
  if (res.ok) {
    fb.innerHTML = `<span class="feedback-ok">${ICON.ok} ${esc(res.student.name)} marked present</span>`;
    input.value = '';
    loadAttendance();
  } else if (res.error?.includes('already marked')) {
    fb.innerHTML = `<span class="feedback-warn">${ICON.warn} ${esc(res.error)}</span>`;
    input.select();
  } else {
    fb.innerHTML = `<span class="feedback-err">${ICON.err} ${esc(res.error)}</span>`;
    input.select();
  }
  setTimeout(() => { fb.innerHTML = ''; }, 3000);
}

async function undoMark(studentId) {
  await api('DELETE', `/api/sessions/${currentSession.id}/attendance/${studentId}`);
  loadAttendance();
  toast('Mark removed');
}


// ── ═══════════ PHOTO ATTENDANCE (file upload) ═══════════ ────────────────────

function toggleFaceRec() {
  const panel = document.getElementById('face-rec-panel');
  const btn   = document.getElementById('face-toggle-btn');
  const open  = panel.style.display === 'none' || panel.style.display === '';
  if (open) closeLiveCam();
  panel.style.display = open ? 'block' : 'none';
  btn.innerHTML = open ? `${ICON.close} Hide Photo` : `${ICON.cam} Photo Attendance`;
  if (!open) resetFaceRecPanel();
}

function closeFaceRec() {
  document.getElementById('face-rec-panel').style.display = 'none';
  document.getElementById('face-toggle-btn').innerHTML = `${ICON.cam} Photo Attendance`;
}

function resetFaceRecPanel() {
  facePhotoFile = null;
  const fileInput   = document.getElementById('face-file');
  if (fileInput) fileInput.value = '';
  const dropInner   = document.getElementById('face-drop-inner');
  const previewWrap = document.getElementById('face-preview-wrap');
  if (dropInner)   dropInner.style.display   = '';
  if (previewWrap) previewWrap.style.display  = 'none';
  const fb = document.getElementById('face-feedback');
  if (fb) fb.innerHTML = '';
  const rp = document.getElementById('face-results-panel');
  if (rp) rp.style.display = 'none';
}

function initFaceDropZone() {
  const zone  = document.getElementById('face-drop-zone');
  const input = document.getElementById('face-file');
  if (!zone || !input) return;
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', e => { if (!zone.contains(e.relatedTarget)) zone.classList.remove('drag-over'); });
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) setFacePhoto(file);
  });
  input.addEventListener('change', () => { if (input.files[0]) setFacePhoto(input.files[0]); });
}

function setFacePhoto(file) {
  if (!file.type.startsWith('image/')) { toast('Please select an image file'); return; }
  facePhotoFile = file;
  const reader = new FileReader();
  reader.onload = ev => {
    document.getElementById('face-preview-img').src = ev.target.result;
    document.getElementById('face-drop-inner').style.display   = 'none';
    document.getElementById('face-preview-wrap').style.display = 'block';
  };
  reader.readAsDataURL(file);
}

function clearFacePhoto() {
  facePhotoFile = null;
  document.getElementById('face-file').value = '';
  document.getElementById('face-preview-img').src = '';
  document.getElementById('face-drop-inner').style.display   = '';
  document.getElementById('face-preview-wrap').style.display = 'none';
}

async function processFaceAttendance() {
  const fb = document.getElementById('face-feedback');
  if (!facePhotoFile) { fb.innerHTML = `<span class="feedback-err">${ICON.err} Please choose a group photo first</span>`; return; }
  if (!currentSession) { fb.innerHTML = `<span class="feedback-err">${ICON.err} No session selected</span>`; return; }

  const fd = new FormData();
  fd.append('photo', facePhotoFile);

  showOverlay('Recognizing faces…', 'This may take a moment on first run while the model loads');
  try {
    const res  = await fetch(`/api/sessions/${currentSession.id}/face-attend`, { method: 'POST', body: fd });
    const data = await res.json();
    hideOverlay();
    if (!res.ok) {
      fb.innerHTML = `<span class="feedback-err">${ICON.err} ${esc(data.error || 'Processing failed')}</span>`;
      return;
    }
    fb.innerHTML = '';
    renderFaceResults('face-stats', 'face-annotated-img', 'face-recognized-list', data, true);
    document.getElementById('face-results-panel').style.display = 'block';
    loadAttendance();
  } catch {
    hideOverlay();
    fb.innerHTML = `<span class="feedback-err">${ICON.err} Network error — is the server running?</span>`;
  }
}


// ── ═══════════ LIVE CAMERA ATTENDANCE ═══════════ ────────────────────────────

async function toggleLiveCam() {
  const panel = document.getElementById('live-cam-panel');
  const btn   = document.getElementById('live-cam-btn');
  const open  = panel.style.display === 'none' || panel.style.display === '';
  if (open) {
    closeFaceRec();
    panel.style.display = 'block';
    btn.innerHTML = `${ICON.close} Hide Camera`;
    attStream = await startCamera(document.getElementById('att-video'));
    if (!attStream) { panel.style.display = 'none'; btn.innerHTML = `${ICON.vid} Live Camera`; }
  } else {
    closeLiveCam();
  }
}

function closeLiveCam() {
  stopAutoScan();
  stopStream(attStream);
  attStream = null;
  const panel = document.getElementById('live-cam-panel');
  const btn   = document.getElementById('live-cam-btn');
  if (panel) panel.style.display = 'none';
  if (btn)   btn.innerHTML = `${ICON.vid} Live Camera`;
  const rp = document.getElementById('live-results-panel');
  if (rp) rp.style.display = 'none';
  const cb = document.getElementById('autoscan-cb');
  if (cb) cb.checked = false;
}

async function scanLiveFrame() {
  if (!currentSession) return;
  const video = document.getElementById('att-video');
  const fb    = document.getElementById('live-cam-feedback');

  if (!attStream || !video.srcObject) {
    fb.innerHTML = `<span class="feedback-err">${ICON.err} Camera not active</span>`;
    return;
  }

  fb.innerHTML = `<span class="feedback-warn">${ICON.warn} Scanning…</span>`;

  const blob = await captureFrame(video);
  const fd   = new FormData();
  fd.append('photo', blob, 'scan.jpg');

  try {
    const res  = await fetch(`/api/sessions/${currentSession.id}/face-attend`, { method: 'POST', body: fd });
    if (res.status === 401) { window.location.href = '/login'; return; }
    const data = await res.json();
    if (!res.ok) {
      fb.innerHTML = `<span class="feedback-err">${ICON.err} ${esc(data.error || 'Scan failed')}</span>`;
      return;
    }
    const m = (data.marked || []).length;
    const s = (data.skipped || []).length;
    fb.innerHTML = `<span class="feedback-ok">${ICON.ok} ${m} newly marked, ${s} already in</span>`;
    renderFaceResults('live-face-stats', null, 'live-recognized-list', data, false);
    document.getElementById('live-results-panel').style.display = 'block';
    if (m > 0) loadAttendance();
  } catch {
    fb.innerHTML = `<span class="feedback-err">${ICON.err} Network error</span>`;
  }
}

function toggleAutoScan(enabled) {
  if (enabled) {
    scanLiveFrame();
    autoScanInterval = setInterval(scanLiveFrame, 3000);
  } else {
    stopAutoScan();
  }
}

function stopAutoScan() {
  if (autoScanInterval) { clearInterval(autoScanInterval); autoScanInterval = null; }
}


// ── Shared face results renderer ───────────────────────────────────────────────

function renderFaceResults(statsId, annotatedId, listId, data, showAnnotated) {
  const total   = data.total_faces || 0;
  const marked  = (data.marked  || []).length;
  const skipped = (data.skipped || []).length;
  const unknown = data.unknown_count || 0;

  document.getElementById(statsId).innerHTML = `
    <div class="face-stat">
      <div class="face-stat-val">${total}</div>
      <div class="face-stat-lbl">Detected</div>
    </div>
    <div class="face-stat ok">
      <div class="face-stat-val">${marked}</div>
      <div class="face-stat-lbl">Newly Marked</div>
    </div>
    <div class="face-stat">
      <div class="face-stat-val">${skipped}</div>
      <div class="face-stat-lbl">Already In</div>
    </div>
    <div class="face-stat bad">
      <div class="face-stat-val">${unknown}</div>
      <div class="face-stat-lbl">Unknown</div>
    </div>`;

  if (showAnnotated && annotatedId) {
    const img = document.getElementById(annotatedId);
    if (data.annotated_photo) {
      img.src = `/uploads/${data.annotated_photo}?t=${Date.now()}`;
      img.style.display = 'block';
    } else {
      img.style.display = 'none';
    }
  }

  const all       = [...(data.marked || []), ...(data.skipped || [])].sort((a, b) => b.confidence - a.confidence);
  const isSkipped = new Set((data.skipped || []).map(s => s.student_id));

  document.getElementById(listId).innerHTML = all.length
    ? all.map(p => `
        <div class="face-rec-row${isSkipped.has(p.student_id) ? ' already' : ''}">
          <span class="face-rec-name">${esc(p.name)}</span>
          <span style="font-size:12px;color:var(--muted);font-family:monospace">${esc(p.index_number || '')}</span>
          <span class="face-conf-badge">${p.confidence}%</span>
          ${isSkipped.has(p.student_id) ? '<span style="font-size:11px;color:var(--muted)">already marked</span>' : ''}
        </div>`).join('')
    : '<div style="font-size:13px;color:var(--muted)">No enrolled students recognized.</div>';
}


// ── Init ───────────────────────────────────────────────────────────────────────
showPage('classes');
initFaceDropZone();

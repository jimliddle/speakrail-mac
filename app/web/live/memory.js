// Single-user editor. Personal text stays out of markup and browser storage.
(async () => {
  window.addEventListener('hashchange', () => {
    if (new URLSearchParams(location.hash.slice(1)).has('memory-key')) location.reload();
  });
  const go = document.getElementById('go'); go.disabled = true;
  const key = new URLSearchParams(location.hash.slice(1)).get('memory-key');
  history.replaceState(null, '', location.pathname);
  try {
    if (key) {
      const response = await fetch('/memory/connect', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({key})});
      if (!response.ok) throw Error('Memory access denied.');
    }
    if (!(await fetch('/memory', {cache:'no-store'})).ok) throw Error('Open the memory launch link from Terminal.');
    go.disabled = false;
  } catch (error) { go.textContent = error.message; return; }
  Object.assign(TOOL_TITLE, {record_note:'Memory proposal', change_memory:'Memory proposal', recall_memory:'Memory recall', confirm_memory:'Memory confirmation'});
  const style = document.createElement('style');
  style.textContent = `
    #memory-dialog{background:#101713;color:#eee;border:1px solid #46534a;border-radius:8px;width:min(760px,94vw);max-height:90dvh;padding:18px;overflow:auto}
    #memory-dialog::backdrop{background:#000b}
    #memory-dialog header,#memory-dialog footer{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
    #memory-dialog h2{font-size:20px;flex:1;margin:0}
    #memory-dialog select,#memory-dialog textarea{display:block;width:100%;box-sizing:border-box;background:#080d0a;color:#eee;border:1px solid #58635b;border-radius:4px;padding:10px;font:inherit;margin:8px 0}
    #memory-dialog textarea{height:280px;max-height:40dvh;resize:vertical;font-size:14px;line-height:1.5;letter-spacing:0}
    #memory-dialog label{display:block;margin-top:12px;font-size:14px}
    #memory-status{font-size:13px;min-height:1.5em;overflow-wrap:anywhere}
    #memory-proposal{border-top:1px solid #46534a;padding-top:12px;margin-top:14px}
    #memory-proposal pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:140px;overflow:auto;font:inherit;font-size:14px}
  `;
  document.head.append(style);
  const opener = document.createElement('button');
  opener.id = 'memory-open'; opener.className = 'chip'; opener.textContent = 'Memory';
  const row = document.createElement('div'); row.className = 'row'; row.append(opener);
  document.getElementById('panel').append(row);
  const dialog = document.createElement('dialog'); dialog.id = 'memory-dialog';
  dialog.setAttribute('aria-labelledby', 'memory-heading');
  dialog.innerHTML = `<header><h2 id="memory-heading">Local memory</h2><button class="chip" id="memory-close" aria-label="Close memory" title="Close memory">&#215;</button></header>
    <label for="memory-file">File</label><select id="memory-file"></select>
    <label for="memory-text">Text</label><textarea id="memory-text" spellcheck="true"></textarea>
    <p id="memory-status" role="status"></p>
    <footer><button class="chip" id="memory-save">Save</button><button class="chip" id="memory-new">New note</button><button class="chip" id="memory-delete">Delete note</button><button class="chip" id="memory-reload">Reload</button></footer>
    <section id="memory-proposal" hidden><h3>Pending voice change</h3><pre id="memory-pending-text"></pre><button class="chip" id="memory-confirm">Confirm change</button> <button class="chip" id="memory-cancel">Discard change</button></section>`;
  document.body.append(dialog);
  const el = id => document.getElementById('memory-' + id);
  let files = [], selected = null, pending = null, busy = false, active = false, dirty = false;
  const status = text => { el('status').textContent = text; };
  function controls() {
    for (const id of ['save', 'new', 'delete']) el(id).disabled = busy || active;
    el('delete').disabled ||= !selected || ['persona', 'profile'].includes(selected.id);
    el('text').readOnly = busy || active;
    for (const id of ['reload', 'file', 'confirm', 'cancel']) el(id).disabled = busy;
    el('text').maxLength = selected && ['persona', 'profile'].includes(selected.id) ? 2000 : 4000;
  }
  async function request(body) {
    const response = await fetch('/memory', body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {cache: 'no-store'});
    if (!response.ok) throw Error(await response.text());
    return response.json();
  }
  function choose(id) {
    selected = files.find(file => file.id === id) || null;
    el('text').value = selected?.text || ''; dirty = false; controls();
  }
  async function reload() {
    const data = await request(); files = data.files; active = data.active; pending = data.pending;
    const old = selected?.id;
    el('file').replaceChildren(...files.map(file => {
      const option = document.createElement('option'); option.value = file.id;
      option.textContent = ['persona', 'profile'].includes(file.id) ? file.id + '.md' : (file.text.split('\n').find(line => line.trim()) || file.id).slice(0, 70);
      return option;
    }));
    el('file').value = files.some(file => file.id === old) ? old : 'persona';
    choose(el('file').value);
    el('proposal').hidden = !pending;
    el('pending-text').textContent = pending ? `${pending.action}: ${pending.id || 'new note'}\n${pending.text}` : '';
    status(active ? 'Voice session active. Stop it to edit files. Pending voice changes can be confirmed here.' : 'Changes apply to the next voice session.');
  }
  async function perform(action) {
    if (busy) return;
    busy = true; controls();
    try { await action(); } catch (error) { status(error.message); }
    finally { busy = false; controls(); }
  }
  const discard = () => !dirty || window.confirm('Discard unsaved edits?');
  opener.onclick = () => { dialog.showModal(); perform(reload); };
  el('close').onclick = () => { if (discard()) dialog.close(); };
  dialog.addEventListener('cancel', event => { if (!discard()) event.preventDefault(); });
  el('text').oninput = () => { dirty = true; };
  el('file').onchange = () => {
    if (discard()) choose(el('file').value);
    else el('file').value = selected?.id || '';
  };
  el('reload').onclick = () => { if (discard()) perform(reload); };
  el('new').onclick = () => {
    if (!discard()) return;
    selected = null; el('file').value = ''; el('text').value = ''; dirty = false; controls(); el('text').focus();
  };
  el('save').onclick = () => perform(async () => {
    await request({action: selected ? 'update' : 'save', id: selected?.id || '', revision: selected?.revision || '', text: el('text').value});
    await reload(); status('Saved locally. Start a new voice session to use updated profile or persona text.');
  });
  el('delete').onclick = () => {
    if (!selected || !window.confirm('Delete this saved note? This cannot be undone.')) return;
    perform(async () => { await request({action: 'forget', id: selected.id, revision: selected.revision}); selected = null; await reload(); status('Note deleted.'); });
  };
  for (const action of ['confirm', 'cancel']) el(action).onclick = () => perform(async () => {
    await request({action, proposal: pending}); await reload(); status(action === 'confirm' ? 'Memory change saved locally.' : 'Voice change discarded.');
  });
})();

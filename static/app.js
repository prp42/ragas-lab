(function () {
  'use strict';

  const METRICS = [
    { k: 'context_recall', name: 'Context Recall', ko: '맥락 재현율', side: 'r' },
    { k: 'context_precision', name: 'Context Precision', ko: '맥락 정밀도', side: 'r' },
    { k: 'faithfulness', name: 'Faithfulness', ko: '충실성', side: 'g' },
    { k: 'answer_relevancy', name: 'Answer Relevancy', ko: '답변 관련성', side: 'g' }
  ];
  const STATUS = { queued: '대기 중', collecting: '답변 수집 중', scoring: '채점 중', done: '완료', failed: '실패' };
  const $ = (s, root) => (root || document).querySelector(s);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (v) => (v === null || v === undefined ? '–' : Number(v).toFixed(2));
  const tone = (v) => (v === null || v === undefined ? 'plain' : v >= 0.75 ? 'good' : v >= 0.45 ? 'warn' : 'bad');

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
    del(k) { try { localStorage.removeItem(k); } catch { /* storage unavailable */ } }
  };

  let auth = { code: store.get('rl.code') || '', id: store.get('rl.id') || '' };
  let me = null;
  let sample = { questions: [], attacks: [] };
  let pollTimer = null;
  let attackPollTimer = null;

  async function api(path, opts) {
    const o = opts || {};
    const resp = await fetch(path, {
      method: o.method || 'GET',
      headers: Object.assign({ 'X-Class-Code': auth.code, 'X-Student-Id': auth.id }, o.body ? { 'Content-Type': 'application/json' } : {}),
      body: o.body ? JSON.stringify(o.body) : undefined
    });
    if (!resp.ok) {
      let msg = `요청이 실패했습니다 (${resp.status}).`;
      try {
        const j = await resp.json();
        if (typeof j.detail === 'string') msg = j.detail;
        else if (Array.isArray(j.detail)) msg = '입력값을 확인하세요: ' + j.detail.map((d) => d.msg).join(', ');
      } catch { /* not json */ }
      const err = new Error(msg);
      err.status = resp.status;
      throw err;
    }
    return o.raw ? resp : resp.json();
  }

  function showError(el, msg) { el.textContent = msg; el.hidden = !msg; }

  // ---------- login ----------
  async function enter() {
    me = await api('/api/me');
    sample = await api('/api/sample');
    $('#login').hidden = true;
    $('#appView').hidden = false;
    $('#who').hidden = false;
    if (me.local_mode) {
      $('#whoId').textContent = '내 컴퓨터에서 실행 중';
      $('#quotaEval').hidden = true;
      $('#quotaAttack').hidden = true;
      $('#logoutBtn').hidden = true;
    } else {
      $('#whoId').textContent = me.is_teacher ? `${me.student_id} (교사)` : me.student_id;
    }
    $('#link').placeholder = `${me.dify_base_url}/chat/xxxxxxxxxxxxxxxx`;
    renderQuota();
    $('#attackPreview').innerHTML = sample.attacks.map((a) => `<li><b>${esc(a.rail)}</b> · ${esc(a.question)}</li>`).join('');
    const savedLink = store.get('rl.link');
    if (savedLink) $('#link').value = savedLink;
    loadDraft();
  }

  function renderQuota() {
    const q = (x) => (x.limit === null ? `${x.used}회 (무제한)` : `${x.used}/${x.limit}회`);
    $('#quotaEval').textContent = `오늘 평가 ${q(me.quota.eval)}`;
    $('#quotaAttack').textContent = `점검 ${q(me.quota.attack)}`;
  }

  async function refreshMe() { try { me = await api('/api/me'); renderQuota(); } catch { /* keep old */ } }

  $('#loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    auth = { code: $('#classCode').value.trim(), id: $('#studentId').value.trim() };
    try {
      await enter();
      store.set('rl.code', auth.code);
      store.set('rl.id', auth.id);
      showError($('#loginError'), '');
    } catch (err) {
      showError($('#loginError'), err.message);
    }
  });

  $('#logoutBtn').addEventListener('click', () => {
    store.del('rl.code'); store.del('rl.id');
    location.reload();
  });

  // ---------- tabs ----------
  document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((x) => x.classList.toggle('on', x === t));
    document.querySelectorAll('.tabpane').forEach((p) => { p.hidden = p.id !== t.dataset.tab; });
    if (t.dataset.tab === 'historyTab') loadHistory();
  }));

  // ---------- step 1: link ----------
  $('#checkBtn').addEventListener('click', async () => {
    const box = $('#checkResult');
    box.hidden = false;
    box.innerHTML = '<p class="muted">확인 중…</p>';
    try {
      const info = await api('/api/check', { method: 'POST', body: { link: $('#link').value.trim() } });
      store.set('rl.link', $('#link').value.trim());
      const warns = [];
      if (!info.citations_enabled) warns.push('<p class="error">검색 근거를 받을 수 없습니다. Dify 앱의 Features에서 <b>Citations and Attributions</b>를 켜고 다시 게시하세요. 끄고 측정하면 Context 지표와 Faithfulness가 0에 가깝게 나옵니다.</p>');
      if (info.required_inputs.length) warns.push(`<p class="error">이 앱은 필수 입력값(${esc(info.required_inputs.join(', '))})이 있어 질문만으로 실행할 수 없습니다. 입력값을 선택 사항으로 바꾸세요.</p>`);
      box.innerHTML = `<div class="row"><span class="chip good">연결됨</span><b>${esc(info.app_name)}</b><span class="chip ${info.citations_enabled ? 'good' : 'bad'}">근거 인용 ${info.citations_enabled ? '켜짐' : '꺼짐'}</span></div>${warns.join('')}`;
    } catch (err) {
      box.innerHTML = `<p class="error">${esc(err.message)}</p>`;
    }
  });

  // ---------- step 2: questions ----------
  function rowHtml(q, i) {
    return `<div class="qrow" data-i="${i}">
      <span class="n">${i + 1}</span>
      <textarea class="q" rows="2" maxlength="500" aria-label="질문 ${i + 1}" placeholder="질문">${esc(q.question)}</textarea>
      <textarea class="qref" rows="2" maxlength="2000" aria-label="정답 ${i + 1}" placeholder="정답 (선택)">${esc(q.reference)}</textarea>
      <button type="button" class="del" aria-label="질문 ${i + 1} 삭제">✕</button></div>`;
  }
  function readRows() {
    return [...document.querySelectorAll('.qrow')].map((r) => ({ question: $('.q', r).value, reference: $('.qref', r).value }));
  }
  function renderRows(rows) {
    const max = me ? me.max_questions : 10;
    const list = rows.slice(0, max);
    if (!list.length) list.push({ question: '', reference: '' });
    $('#qRows').innerHTML = list.map(rowHtml).join('');
    updateCount();
  }
  function updateCount() {
    const rows = readRows().filter((r) => r.question.trim());
    const withRef = rows.filter((r) => r.reference.trim()).length;
    $('#qCount').textContent = `${rows.length}/${me ? me.max_questions : 10}개 · 정답 있음 ${withRef}`;
    $('#addRowBtn').disabled = document.querySelectorAll('.qrow').length >= (me ? me.max_questions : 10);
    store.set('rl.draft', JSON.stringify(readRows()));
  }
  function loadDraft() {
    let rows = [];
    try { rows = JSON.parse(store.get('rl.draft') || '[]'); } catch { rows = []; }
    renderRows(rows);
  }
  $('#qRows').addEventListener('input', updateCount);
  $('#qRows').addEventListener('click', (e) => {
    const b = e.target.closest('.del');
    if (!b) return;
    const rows = readRows();
    rows.splice(Number(b.closest('.qrow').dataset.i), 1);
    renderRows(rows);
  });
  $('#addRowBtn').addEventListener('click', () => { renderRows(readRows().concat([{ question: '', reference: '' }])); });
  $('#sampleBtn').addEventListener('click', () => { renderRows(sample.questions.map((q) => ({ question: q.question, reference: q.reference }))); });
  $('#clearBtn').addEventListener('click', () => renderRows([]));
  $('#pasteToggle').addEventListener('click', () => { $('#pasteBox').hidden = !$('#pasteBox').hidden; });
  $('#pasteApply').addEventListener('click', () => {
    const parsed = $('#pasteArea').value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
      const parts = line.includes('\t') ? line.split('\t') : line.split(',');
      return { question: (parts[0] || '').trim(), reference: parts.slice(1).join(line.includes('\t') ? ' ' : ',').trim() };
    }).filter((r) => r.question && !/^질문$|^question$/i.test(r.question));
    const keep = readRows().filter((r) => r.question.trim());
    renderRows(keep.concat(parsed));
    $('#pasteArea').value = '';
    $('#pasteBox').hidden = true;
  });

  // ---------- step 3: run ----------
  $('#runBtn').addEventListener('click', async () => {
    const questions = readRows().filter((r) => r.question.trim());
    if (!questions.length) { showError($('#runError'), '질문을 하나 이상 입력하세요.'); return; }
    $('#runBtn').disabled = true;
    try {
      const { run_id } = await api('/api/runs', { method: 'POST', body: { link: $('#link').value.trim(), questions } });
      showError($('#runError'), '');
      store.set('rl.link', $('#link').value.trim());
      refreshMe();
      watchRun(run_id, $('#runView'));
    } catch (err) {
      showError($('#runError'), err.message);
    } finally {
      $('#runBtn').disabled = false;
    }
  });

  function watchRun(runId, target) {
    clearTimeout(pollTimer);
    target.hidden = false;
    const tick = async () => {
      try {
        const run = await api(`/api/runs/${runId}`);
        target.innerHTML = renderRun(run);
        bindRun(run, target);
        if (run.status !== 'done' && run.status !== 'failed') pollTimer = setTimeout(tick, 2500);
        else refreshMe();
      } catch (err) {
        target.innerHTML = `<div class="panel"><p class="error">${esc(err.message)}</p></div>`;
      }
    };
    tick();
  }

  function progressPanel(run) {
    const pct = run.status === 'scoring' ? 100 : run.total ? Math.round((run.progress / run.total) * 100) : 0;
    const note = run.status === 'scoring' ? '판사 LLM이 채점하고 있습니다. 질문 수에 따라 1~3분 걸립니다.' : run.status === 'queued' ? '다른 학생의 실행이 끝나기를 기다리는 중입니다.' : `질문 ${run.progress}/${run.total}`;
    return `<div class="panel stack"><div class="row between"><h2>${STATUS[run.status] || esc(run.status)}</h2><span class="muted mono">${esc(run.created_at.slice(0, 16).replace('T', ' '))}</span></div>
      <div class="progress" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><i style="width:${pct}%"></i></div><p class="muted">${note}</p></div>`;
  }

  function renderRun(run) {
    if (run.status === 'failed') return `<div class="panel stack"><h2>실패</h2><p class="error">${esc(run.error)}</p><p class="muted">실패한 실행은 하루 횟수에 포함되지 않습니다.</p></div>`;
    if (run.status !== 'done') return progressPanel(run);
    const r = run.result;
    const s = r.summary;
    const tiles = METRICS.map((m) => `<div class="tile ${m.side}"><span class="v" style="color:var(--${tone(s[m.k]) === 'plain' ? 'muted' : tone(s[m.k])})">${fmt(s[m.k])}</span><span class="l">${m.name} · ${m.ko}</span></div>`).join('');
    const findings = r.findings.length
      ? r.findings.map((f) => `<div class="finding"><span class="chip ${f.stage === '검색' ? 'ret' : 'gen'}">${esc(f.stage)}</span><div><p><b>${esc(METRICS.find((m) => m.k === f.metric).name)} ${fmt(f.score)}</b> · ${esc(f.diagnosis)}</p><p class="muted">처방: ${esc(f.prescription)}</p></div></div>`).join('')
      : '<p class="muted">측정한 지표가 모두 기준선 이상입니다. 더 어려운 질문(여러 문서에 걸친 질문, 답이 없는 질문)을 추가해 보세요.</p>';
    const order = r.items.map((it, i) => i).sort((a, b) => (r.items[a].scores.faithfulness ?? 2) - (r.items[b].scores.faithfulness ?? 2));
    const items = order.map((i) => {
      const it = r.items[i];
      const chips = METRICS.map((m) => `<span class="chip ${tone(it.scores[m.k])}" title="${m.name}">${m.name.split(' ').map((w) => w[0]).join('')} ${fmt(it.scores[m.k])}</span>`).join('');
      const ctx = it.contexts.length ? it.contexts.map((c, j) => `<details><summary class="muted">근거 #${j + 1} · ${esc(it.documents[j] || '')}</summary><div class="ctx">${esc(c)}</div></details>`).join('') : '<p class="error">검색 근거가 없습니다.</p>';
      return `<details class="item"><summary><span class="q">${esc(it.question)}</span>${chips}<span class="muted mono">${it.latency_s}s</span></summary>
        <div class="item-body">${it.reference ? `<div><span class="eyebrow">정답</span><div class="ref">${esc(it.reference)}</div></div>` : '<p class="muted">정답 없음: 검색 지표는 재지 않았습니다. 답이 없는 질문이라면 "모른다"고 답했는지 직접 확인하세요.</p>'}
        <div><span class="eyebrow gen">답변</span><div class="answer">${esc(it.answer)}</div></div>
        <div class="stack"><span class="eyebrow ret">검색된 근거</span>${ctx}</div></div></details>`;
    }).join('');
    return `<div class="panel stack"><div class="row between"><h2>결과</h2><span class="muted mono">${esc(run.created_at.slice(0, 16).replace('T', ' '))} · 평균 ${r.avg_latency_s}s · 판사 ${esc(r.judge_model)}</span></div>
        <div class="tiles">${tiles}</div>
        <div class="row"><button type="button" class="btn ghost" data-act="csv">CSV 내려받기</button><label class="muted" for="cmp-${run.id}">이전 실행과 비교</label><select id="cmp-${run.id}" data-act="cmp" style="width:auto"><option value="">선택…</option></select></div>
        <div class="cmp scroll"></div></div>
      <div class="panel stack"><h2>진단 <span class="slide">슬라이드 18</span></h2><p class="muted">검색이 무너지면 생성은 구제할 수 없습니다. 위에서부터 고치세요.</p>${findings}</div>
      <div class="panel stack"><h2>질문별 결과 <span class="slide">슬라이드 12</span></h2><p class="muted">Faithfulness가 낮은 순서입니다. 평균보다 낮은 케이스를 먼저 열어 보세요.</p>${items}</div>`;
  }

  function bindRun(run, target) {
    if (run.status !== 'done') return;
    const csvBtn = target.querySelector('[data-act="csv"]');
    if (csvBtn) csvBtn.addEventListener('click', async () => {
      try {
        const resp = await api(`/api/runs/${run.id}/csv`, { raw: true });
        const url = URL.createObjectURL(await resp.blob());
        const a = document.createElement('a');
        a.href = url; a.download = `ragas_${run.id.slice(0, 8)}.csv`;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 2000);
      } catch (err) { alertInline(target, err.message); }
    });
    const sel = target.querySelector('[data-act="cmp"]');
    if (sel) {
      api('/api/runs').then((runs) => {
        runs.filter((x) => x.kind === 'eval' && x.status === 'done' && x.id !== run.id).forEach((x) => {
          const o = document.createElement('option');
          o.value = x.id;
          o.textContent = `${x.created_at.slice(5, 16).replace('T', ' ')} · ${x.app_code.slice(0, 6)}${me.is_teacher ? ' · ' + x.student_id : ''}`;
          sel.appendChild(o);
        });
      }).catch(() => {});
      sel.addEventListener('change', async () => {
        const box = target.querySelector('.cmp');
        if (!sel.value) { box.innerHTML = ''; return; }
        const other = await api(`/api/runs/${sel.value}`);
        const a = other.result.summary, b = run.result.summary;
        box.innerHTML = `<table><thead><tr><th>지표</th><th class="num">이전</th><th class="num">이번</th><th class="num">변화</th></tr></thead><tbody>${METRICS.map((m) => {
          const d = a[m.k] != null && b[m.k] != null ? b[m.k] - a[m.k] : null;
          const cls = d == null ? 'plain' : Math.abs(d) < 0.05 ? 'plain' : d > 0 ? 'good' : 'bad';
          return `<tr><td>${m.name}</td><td class="num">${fmt(a[m.k])}</td><td class="num">${fmt(b[m.k])}</td><td class="num"><span class="chip ${cls}">${d == null ? '–' : (d >= 0 ? '+' : '') + d.toFixed(2)}</span></td></tr>`;
        }).join('')}</tbody></table><p class="muted" style="font-size:13px">±0.05보다 작은 변화는 판사 잡음일 수 있습니다. 같은 질문으로 비교했는지도 확인하세요.</p>`;
      });
    }
  }

  function alertInline(target, msg) {
    const p = document.createElement('p');
    p.className = 'error'; p.textContent = msg;
    target.prepend(p);
  }

  // ---------- history ----------
  async function loadHistory() {
    try {
      const runs = await api('/api/runs');
      const head = `<thead><tr><th>시각</th>${me.is_teacher ? '<th>학번</th>' : ''}<th>종류</th><th>앱</th><th>상태</th>${METRICS.map((m) => `<th class="num">${m.name.split(' ').map((w) => w[0]).join('')}</th>`).join('')}</tr></thead>`;
      const body = runs.map((r) => `<tr class="click" data-id="${esc(r.id)}" data-kind="${esc(r.kind)}"><td class="mono">${esc(r.created_at.slice(5, 16).replace('T', ' '))}</td>${me.is_teacher ? `<td class="mono">${esc(r.student_id)}</td>` : ''}
        <td>${r.kind === 'eval' ? '평가' : '점검'}</td><td class="mono">${esc(r.app_code.slice(0, 6))}…</td><td><span class="chip ${r.status === 'done' ? 'good' : r.status === 'failed' ? 'bad' : 'warn'}">${STATUS[r.status] || esc(r.status)}</span></td>
        ${METRICS.map((m) => `<td class="num">${r.summary ? fmt(r.summary[m.k]) : ''}</td>`).join('')}</tr>`).join('');
      $('#historyTable').innerHTML = head + `<tbody>${body || '<tr><td colspan="9" class="muted">아직 실행 기록이 없습니다.</td></tr>'}</tbody>`;
    } catch (err) {
      $('#historyTable').innerHTML = `<tbody><tr><td class="error">${esc(err.message)}</td></tr></tbody>`;
    }
  }
  $('#refreshBtn').addEventListener('click', loadHistory);
  $('#historyTable').addEventListener('click', (e) => {
    const tr = e.target.closest('tr[data-id]');
    if (!tr) return;
    if (tr.dataset.kind === 'eval') watchRun(tr.dataset.id, $('#historyRun'));
    else watchAttack(tr.dataset.id, $('#historyRun'));
    $('#historyRun').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  // ---------- guardrail check ----------
  $('#attackBtn').addEventListener('click', async () => {
    $('#attackBtn').disabled = true;
    try {
      const { run_id } = await api('/api/attacks', { method: 'POST', body: { link: $('#link').value.trim() } });
      showError($('#attackError'), '');
      refreshMe();
      watchAttack(run_id, $('#attackView'));
    } catch (err) {
      showError($('#attackError'), err.message === '요청이 실패했습니다 (422).' ? '평가 실행 탭에서 앱 링크를 먼저 입력하세요.' : err.message);
    } finally {
      $('#attackBtn').disabled = false;
    }
  });

  function watchAttack(runId, target) {
    clearTimeout(attackPollTimer);
    const tick = async () => {
      const run = await api(`/api/runs/${runId}`);
      if (run.status === 'failed') { target.innerHTML = `<div class="panel"><p class="error">${esc(run.error)}</p></div>`; return; }
      const items = (run.result && run.result.items) || [];
      const done = run.status === 'done';
      target.innerHTML = (done ? '' : progressPanel(run)) + `<div class="panel stack"><div class="row between"><h2>점검 결과</h2><span class="muted" data-tally></span></div>${items.map((it, i) => `
        <div class="atk panel"><div class="row between"><span class="chip plain">${esc(it.rail)}</span><span class="verdict" data-i="${i}"><button type="button" class="y">막음</button><button type="button" class="n">뚫림</button></span></div>
        <b>${esc(it.question)}</b><span class="muted" style="font-size:13px">기대: ${esc(it.expect)}</span><div class="answer">${esc(it.answer)}</div></div>`).join('')}
        ${done ? '<p class="muted">모두 막혔다면, 그것이 모델 자체의 안전 학습 덕분인지 내가 세운 레일 덕분인지 구분해 보세요. 한 겹은 방어가 아닙니다. <span class="slide">슬라이드 32</span></p>' : ''}</div>`;
      const verdicts = {};
      target.querySelectorAll('.verdict').forEach((v) => v.addEventListener('click', (e) => {
        const b = e.target.closest('button');
        if (!b) return;
        verdicts[v.dataset.i] = b.classList.contains('y');
        v.querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
        const vals = Object.values(verdicts);
        target.querySelector('[data-tally]').textContent = `막음 ${vals.filter(Boolean).length} · 뚫림 ${vals.filter((x) => !x).length}`;
      }));
      if (!done) attackPollTimer = setTimeout(tick, 2500); else refreshMe();
    };
    tick().catch((err) => { target.innerHTML = `<div class="panel"><p class="error">${esc(err.message)}</p></div>`; });
  }

  // ---------- boot ----------
  // Local mode answers /api/me without codes; class mode needs the saved code and student ID.
  enter().catch(() => { $('#login').hidden = false; });
})();

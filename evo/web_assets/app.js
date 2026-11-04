const $ = selector => document.querySelector(selector);
const token = window.EVO_TOKEN;
let selectedTask = null;
const labels = {
  pending: '待审查', accepted: '已接受', changes_requested: '需修改', revising: '修订中',
  execution_failed: '修订失败', success: '执行成功', failed: '执行失败', blocked: '已阻塞', running: '执行中'
};
const pages = {
  tasks: ['任务', '提交目标，查看代理执行与审查进度。'],
  inbox: ['待处理', '需要你审查或答复的事项。'],
  group: ['群聊', '与三个代理一起讨论。'],
  dm: ['私聊', '与一个代理单独交流。'],
  memory: ['记忆', '查看代理积累的经验。']
};

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}
function toast(message) {
  const box = $('#toast'); box.textContent = message; box.style.display = 'block';
  clearTimeout(toast.timer); toast.timer = setTimeout(() => box.style.display = 'none', 4500);
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-Evo-Token': token, ...options.headers }
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || '请求失败');
  return data;
}
function switchView(name) {
  document.querySelectorAll('.nav,.view').forEach(item => item.classList.remove('active'));
  $(`.nav[data-view="${name}"]`).classList.add('active');
  $(`#${name}`).classList.add('active');
  $('#page-title').textContent = pages[name][0];
  $('#page-subtitle').textContent = pages[name][1];
}

async function submit(path, body) {
  try {
    const { job_id } = await api(path, { method: 'POST', body: JSON.stringify(body) });
    toast('已提交，代理正在处理');
    poll(job_id);
  } catch (error) { toast(error.message); }
}
async function poll(jobId) {
  try {
    const job = await api(`/api/jobs/${jobId}`);
    if (job.status === 'waiting') { showQuestion(job); await loadInbox(); return; }
    if (job.status === 'error') { toast(`运行失败：${job.error}`); await refresh(); return; }
    if (job.status === 'done') {
      $('#approval').hidden = true;
      await refresh();
      if (job.kind === 'task' && job.result?.id) { switchView('tasks'); await openTask(job.result.id); }
      toast('运行已结束'); return;
    }
    setTimeout(() => poll(jobId), 1400);
  } catch (error) { toast(error.message); }
}
function showQuestion(job) {
  const question = job.question;
  const clarification = question.kind === 'clarification';
  $('#approval-title').textContent = clarification ? '代理需要补充信息' : '需要批准操作';
  $('#approval-prompt').textContent = question.prompt;
  $('#approval-answer').hidden = !clarification;
  $('#approval-yes').textContent = clarification ? '提交答复' : '批准';
  $('#approval-no').textContent = clarification ? '暂不回答' : '拒绝';
  $('#approval').dataset.job = job.id;
  $('#approval').dataset.kind = question.kind;
  $('#approval').hidden = false;
}
async function answerQuestion(approve) {
  const modal = $('#approval');
  const answer = modal.dataset.kind === 'clarification' ? (approve ? $('#approval-answer').value : '') : approve;
  try {
    await api(`/api/jobs/${modal.dataset.job}/answer`, { method: 'POST', body: JSON.stringify({ answer }) });
    modal.hidden = true; setTimeout(() => poll(modal.dataset.job), 300);
  } catch (error) { toast(error.message); }
}

async function refresh() {
  try {
    const data = await api('/api/overview');
    const reviews = new Map(data.reviews.map(review => [review.root_id, review]));
    const list = $('#task-list'); list.replaceChildren();
    $('#task-count').textContent = String(data.tasks.length);
    if (!data.tasks.length) list.append(node('p', 'empty', '还没有任务'));
    for (const task of data.tasks) {
      const status = reviews.get(task.id)?.status || task.status;
      const button = node('button', `task-item${task.id === selectedTask ? ' selected' : ''}`);
      button.dataset.id = task.id;
      button.append(node('strong', '', task.description));
      const footer = node('footer');
      footer.append(node('span', '', new Date(task.started * 1000).toLocaleString()),
                    node('span', `status ${status}`, labels[status] || status));
      button.append(footer); button.onclick = () => openTask(task.id);
      list.append(button);
    }
    renderMessages('#group-messages', data.group);
    await Promise.all([loadInbox(), loadDm(), loadMemory()]);
  } catch (error) { toast(error.message); }
}
async function loadInbox() {
  try {
    const data = await api('/api/inbox');
    const list = $('#inbox-list'); list.replaceChildren();
    const count = data.reviews.length + data.waiting.length;
    $('#pending-count').textContent = String(count);
    $('#inbox-count').textContent = String(count);
    $('#inbox-count').hidden = count === 0;
    for (const job of data.waiting) {
      const button = node('button', 'inbox-item');
      button.append(node('strong', '', '代理需要答复'), node('small', '', job.question.prompt));
      button.onclick = () => showQuestion(job); list.append(button);
    }
    for (const review of data.reviews) {
      const button = node('button', 'inbox-item');
      button.append(node('strong', '', `任务 ${review.root_id} 等待审查`),
                    node('small', '', '查看结果并决定是否接受'));
      button.onclick = () => { switchView('tasks'); openTask(review.root_id); };
      list.append(button);
    }
    if (!count) list.append(node('p', 'empty', '目前没有待处理事项'));
  } catch (error) { toast(error.message); }
}
async function decideReview(id, decision, feedback = '') {
  try {
    await api(`/api/reviews/${id}`, { method: 'POST', body: JSON.stringify({ decision, feedback }) });
    toast(decision === 'accepted' ? '结果已接受' : '修改意见已保存');
    await refresh(); await openTask(id);
  } catch (error) { toast(error.message); }
}
function formatAction(action) {
  try {
    const value = JSON.parse(action.payload);
    if (value.tool_result) return `${value.tool_result} 完成 · ${JSON.stringify(value.output)}`;
    if (value.tool_error) return `${value.tool_error} 出错 · ${value.error}`;
    if (value.action === 'tool') return `调用 ${value.name} · ${JSON.stringify(value.args || {})}`;
    if (value.action === 'final') return '代理提交最终结果';
    return `${value.action || '操作'} · ${JSON.stringify(value)}`;
  } catch { return action.payload; }
}
async function openTask(id) {
  try {
    selectedTask = id;
    const trace = await api(`/api/trace/${id}`);
    const root = trace.tasks[0], review = trace.review;
    const box = $('#task-detail'); box.replaceChildren();
    const heading = node('div', 'detail-head');
    heading.append(node('h2', '', root.description), node('span', `status ${review?.status || root.status}`, labels[review?.status || root.status] || root.status));
    box.append(heading);
    const elapsed = root.ended ? `${(root.ended - root.started).toFixed(1)} 秒` : '运行中';
    box.append(node('p', 'meta', `${trace.tasks.length - 1} 个子任务 · ${elapsed} · ${id}`));
    if (review?.revision_of) box.append(node('p', 'meta', `修订自任务 ${review.revision_of}`));
    box.append(node('pre', '', root.result || '代理正在执行…'));

    if (review?.status === 'pending') {
      const block = node('div', 'review-block');
      block.append(node('h3', '', '审查结果'), node('p', '', '确认结果，或写下需要修改的地方。'));
      const feedback = node('textarea'); feedback.rows = 2; feedback.placeholder = '修改意见（要求修改时必填）';
      block.append(feedback);
      const actions = node('div', 'review-actions');
      const revise = node('button', 'secondary', '要求修改');
      revise.onclick = () => decideReview(id, 'changes_requested', feedback.value);
      const accept = node('button', 'primary', '接受结果');
      accept.onclick = () => decideReview(id, 'accepted');
      actions.append(revise, accept); block.append(actions); box.append(block);
    } else if (review?.status === 'changes_requested') {
      const block = node('div', 'review-block');
      block.append(node('h3', '', '修改意见'), node('p', '', review.feedback));
      const retry = node('button', 'primary', '根据反馈重跑');
      retry.onclick = () => submit('/api/revisions', { root_id: id });
      block.append(retry); box.append(block);
    }

    const details = node('details', 'trace');
    details.append(node('summary', '', `查看运行记录 · ${trace.actions.length} 条操作`));
    for (const task of trace.tasks.slice(1)) details.append(node('div', 'step', `${task.owner} · ${labels[task.status] || task.status} · ${task.description}`));
    for (const event of trace.review_events || []) details.append(node('div', 'step', `${new Date(event.ts * 1000).toLocaleTimeString()} · 审查 ${labels[event.status] || event.status}${event.feedback ? ' · ' + event.feedback : ''}`));
    for (const action of trace.actions) details.append(node('div', 'step', `${new Date(action.ts * 1000).toLocaleTimeString()} · ${action.agent} · ${formatAction(action)}`));
    box.append(details);
    document.querySelectorAll('.task-item').forEach(button => button.classList.remove('selected'));
    await refreshTaskSelection();
  } catch (error) { toast(error.message); }
}
async function refreshTaskSelection() {
  const items = document.querySelectorAll('.task-item');
  for (const item of items) if (item.dataset.id === selectedTask) item.classList.add('selected');
}
function renderMessages(selector, messages) {
  const box = $(selector); box.replaceChildren();
  if (!messages.length) { box.append(node('p', 'empty', '暂无消息')); return; }
  for (const message of messages) {
    const row = node('div', 'message');
    row.append(node('strong', '', message.sender), node('p', '', message.content));
    box.append(row);
  }
  box.scrollTop = box.scrollHeight;
}
async function loadDm() {
  try { renderMessages('#dm-messages', await api(`/api/dm/${$('#dm-agent').value}`)); }
  catch (error) { toast(error.message); }
}
async function loadMemory() {
  try {
    const data = await api(`/api/memory/${$('#memory-agent').value}`);
    const box = $('#memory-content'); box.replaceChildren();
    const stats = node('div', 'memory-card surface');
    stats.append(node('div', 'stats', `成功 ${data.stats.success || 0} · 失败 ${data.stats.failed || 0}`));
    box.append(stats);
    for (const item of data.recent) {
      const card = node('div', 'memory-card surface');
      card.append(node('strong', '', item.task), node('p', '', item.lesson), node('small', '', item.outcome));
      box.append(card);
    }
  } catch (error) { toast(error.message); }
}

document.querySelectorAll('.nav').forEach(button => button.onclick = () => switchView(button.dataset.view));
$('#run-task').onclick = () => submit('/api/tasks', { text: $('#goal').value });
$('#send-group').onclick = () => submit('/api/group', { text: $('#group-input').value });
$('#send-dm').onclick = () => submit('/api/dm', { text: $('#dm-input').value, agent: $('#dm-agent').value });
$('#refresh').onclick = refresh;
$('#dm-agent').onchange = loadDm;
$('#memory-agent').onchange = loadMemory;
$('#approval-yes').onclick = () => answerQuestion(true);
$('#approval-no').onclick = () => answerQuestion(false);
refresh();

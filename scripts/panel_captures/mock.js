// dados fictícios (demo) para os screenshots: substitui as respostas da API do painel isolado
const now = () => Date.now() / 1000;
const COLORS = { workstation: '#39ff88', server: '#ff7a5c', laptop: '#b388ff' };
function seeded(n) { let x = Math.sin(n * 12.9898) * 43758.5453; return x - Math.floor(x); }
function history(days) {
  const dates = []; const d0 = new Date();
  for (let i = days - 1; i >= 0; i--) { const d = new Date(d0 - i * 86400e3); dates.push(d.toISOString().slice(0, 10)); }
  const hosts = ['laptop', 'server', 'workstation'];
  const tokens = {}; hosts.forEach((h, k) => tokens[h] = dates.map((dt, i) => {
    const wd = new Date(dt + 'T12:00').getDay(); const we = wd == 0 || wd == 6;
    const base = [0.9e6, 2.4e6, 4.2e6][k]; const v = base * (we ? 0.25 : 1) * (0.45 + 1.1 * seeded(i * 3 + k)) * (1 + i / days * 0.6);
    return k == 0 && seeded(i + 7) < 0.35 ? 0 : Math.round(v);
  }));
  const sessions = dates.map((_, i) => Math.round(3 + 9 * seeded(i + 1)));
  const work_s = dates.map((_, i) => Math.round(3600 * (1.5 + 5 * seeded(i + 2))));
  const prompts = dates.map((_, i) => Math.round(20 + 70 * seeded(i + 3)));
  const sum = a => a.reduce((x, y) => x + y, 0);
  const by_host = {}; hosts.forEach((h, k) => by_host[h] = { tokens: sum(tokens[h]), sessions: Math.round(sum(sessions) / 3), work_s: 0, agents: 0 });
  const f = days / 30;
  return { days, dates, hosts, errors: [], tokens, sessions, work_s, prompts, by_host,
    models: [['Opus 5.5', 61e6 * f], ['Sonnet 5.5', 18e6 * f], ['Haiku 5', 3.2e6 * f]].map(([a, b]) => [a, Math.round(b)]),
    tools: [['Bash', 1840], ['Read', 1512], ['Edit', 1104], ['Grep', 702], ['Write', 388], ['WebFetch', 214], ['Glob', 190], ['TodoWrite', 120]].map(([a, b]) => [a, Math.round(b * f)]),
    agents: [['Explore', 164], ['general-purpose', 92], ['Plan', 47], ['code-reviewer', 21]].map(([a, b]) => [a, Math.round(b * f)]) };
}
function patchState(st, lang) {
  const t = now(); const en = lang == 'en';
  st.machine = 'workstation'; st.screen_here = true;
  st.default_colors = COLORS; st.hosts = [['workstation', true], ['server', true], ['laptop', false]];
  st.summary = { sessions: 4, hidden: 1, active: 3, waiting: 1, agents: 4, week: 58, five: 31, tok_today: '2.1M', tok_week: '14.8M',
    list: [
      { label: en ? 'Monitor USB screen' : 'Tela USB do monitor', sub: 'monitor', host: 'workstation', status: 'working', id: 'a', tool: 'Bash', agents: 3, ctx: 41 },
      { label: en ? 'Signup wizard' : 'Assistente de cadastro', sub: 'web-app', host: 'workstation', status: 'waiting', id: 'b', tool: null, agents: 0, ctx: 18 },
      { label: en ? 'Per-plan rate limit' : 'Limite por plano', sub: 'api', host: 'server', status: 'working', id: 'c', tool: 'Edit', agents: 1, ctx: 63 },
      { label: 'qwen3:14b', sub: 'Ollama', host: 'server', status: 'working', id: 'llm', kind: 'llm', tool: null, agents: 0, ctx: null },
      { label: en ? 'Deploy playbook' : 'Playbook de deploy', sub: 'infra', host: 'server', status: 'idle', id: 'd', tool: null, agents: 0, ctx: 9 },
    ] };
  st.machines = [
    { name: 'workstation', up: true, local: true, url: '', seen: null, id: 'w', panel: '', sessions: 2, active: 2, agents: 3, tok_today: 0, cpu: 23, ram: '14/32 GB', gpu: null, ollama: [] },
    { name: 'server', up: true, local: false, url: 'http://192.168.1.10:8787', seen: null, id: 's', panel: 'http://192.168.1.10:8788', sessions: 3, active: 2, agents: 1, cpu: 12, ram: '8/46 GB', gpu: 34, ollama: ['qwen3:14b'] },
    { name: 'laptop', up: false, local: false, url: 'http://192.168.1.12:8787', seen: t - 7200, id: 'l', panel: 'http://192.168.1.12:8788', sessions: 1, active: 0, agents: 0 },
  ];
  st.net = { found: [{ host: 'mini-pc', ip: '192.168.1.31', port: 8787, panel_port: 8788, version: st.version }], pairing: {}, id: 'w',
    discovery: { on: true, port: 8789, listening: true }, token_set: true };
  st.alerts = [
    { key: 'k1', type: 'done', label: en ? 'Deploy playbook' : 'Playbook de deploy', host: 'server', worked_s: 1380, ts: t - 2400 },
    { key: 'k2', type: 'waiting', label: en ? 'Signup wizard' : 'Assistente de cadastro', host: 'workstation', reason: en ? 'permission' : 'permissão', ts: t - 20 },
  ];
  st.peers = ['http://192.168.1.10:8788', 'http://192.168.1.12:8788'];
  return st;
}
function session(id, lang) {
  const t = now(); const en = lang == 'en';
  return { host: 'workstation', _now: t, session: { project: 'monitor', title: en ? 'Monitor USB screen' : 'Tela USB do monitor', status: 'working', tool: 'Bash',
    model: 'Opus 5.5', context_pct: 41, tokens: 31e6, cost_usd: 18.42, since: t - 3 * 3600, last: t - 2,
    subagents: [{ type: 'Explore', tool: 'Grep' }, { type: 'general-purpose', tool: 'WebFetch' }, { type: 'Explore', tool: null }] },
    events: [[3, 'PreToolUse', { tool_name: 'Bash' }], [6, 'PreToolUse', { tool_name: 'Grep', sub: true }], [31, 'SubagentStart', { agent_type: 'Explore' }],
      [58, 'PreToolUse', { tool_name: 'WebFetch', sub: true }], [75, 'PreToolUse', { tool_name: 'Read' }], [200, 'UserPromptSubmit', {}], [420, 'SessionStart', {}]]
      .map(([a, n, x]) => ({ ts: t - a, hook_event_name: n, ...x })) };
}
async function install(page, base, lang) {
  await page.route('**/api/state', async r => { const res = await r.fetch(); const j = await res.json(); await r.fulfill({ json: patchState(j, lang) }) });
  await page.route('**/api/history*', r => { const n = +new URL(r.request().url()).searchParams.get('days') || 30; r.fulfill({ json: history(n) }) });
  await page.route('**/api/session*', r => r.fulfill({ json: session('a', lang) }));
  await page.route('**/api/panel-url', r => r.fulfill({ json: { url: 'http://192.168.1.10:8788/?key=Xk3v9QeLr2…', tela: 'http://192.168.1.10:8788/tela?key=Xk3v9QeLr2…' } }));
  await page.route('**/api/telas', r => r.fulfill({ json: [{ backend: 'turing', kind: 'usb', device: '/dev/ttyACM0' }, { backend: 'web', kind: 'web', device: '/tela' }, { backend: 'terminal', kind: 'terminal', device: '' }] }));
  const DEMO = require('fs').readFileSync(process.env.DEMO_PNG || __dirname + '/demo.png');
  await page.route('**/img/now.png*', async r => { await r.fulfill({ status: 200, body: DEMO, headers: { 'content-type': 'image/png', 'X-Byorzin-Screen': 'workstation', 'Access-Control-Expose-Headers': 'X-Byorzin-Screen' } }) });
  await page.route('**/tela/frame.jpg*', async r => { await r.fulfill({ status: 200, body: DEMO, headers: { 'content-type': 'image/png' } }) });
}
module.exports = { install };

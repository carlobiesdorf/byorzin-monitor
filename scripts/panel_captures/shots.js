// Capturas do painel para o README (docs/img/panel-*.png) com dados fictícios (mock.js).
// Rode contra um painel ISOLADO (XDG_CONFIG_HOME/XDG_STATE_HOME/CLAUDE_CONFIG_DIR temporários,
// portas altas, discovery = false, display.json com "language": "en"):
//   PANEL=http://127.0.0.1:47873 DEMO_PNG=/tmp/demo.png node shots.js docs/img [filtro]
// DEMO_PNG: quadro da prévia (ex.: layout cards em escala 3, 1440x960). CHROMIUM: binário headless.
// Precisa do pacote playwright-core. GIF de uso: node rec.js /tmp/quadros && python togif.py /tmp/quadros docs/img/panel.gif 1200 256
const { chromium } = require('playwright-core');
const { install } = require('./mock.js');
const exe = process.env.CHROMIUM || (process.env.HOME + '/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell');
const B = process.env.PANEL || 'http://127.0.0.1:47873', OUT = process.argv[2], ONLY = process.argv[3], DPR = +(process.env.DPR || 2);
async function shot(b, { name, lang = 'en', theme = 'dark', w = 1440, h = 900, hash = 'tela', act, dpr = DPR, full = false }) {
  if (ONLY && !name.includes(ONLY)) return;
  const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: dpr });
  const p = await ctx.newPage(); const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  await p.addInitScript(([l, t]) => { localStorage.setItem('byorzin.lang', l); localStorage.setItem('byorzin.theme', t) }, [lang, theme]);
  await install(p, B, lang);
  await p.goto(B + '/?lang=' + lang + '#' + hash); await p.waitForTimeout(2500);
  if (act) await act(p);
  await p.waitForTimeout(700);
  await p.screenshot({ path: OUT + '/' + name + '.png', fullPage: full });
  if (errs.length) console.log(name, 'ERRS', errs);
  await p.unrouteAll({ behavior: 'ignoreErrors' }); await ctx.close();
}
(async () => {
  const b = await chromium.launch({ executablePath: exe });
  await shot(b, { name: 'panel-overview' });
  await shot(b, { name: 'panel-session', act: async p => { await p.click('.srow'); await p.waitForTimeout(700) } });
  await shot(b, { name: 'panel-layouts', hash: 'layouts', act: async p => { await p.waitForTimeout(1500) } });
  await shot(b, { name: 'panel-settings', hash: 'ajustes' });
  await shot(b, { name: 'panel-alerts', hash: 'alertas' });
  await shot(b, { name: 'panel-history', hash: 'historico', act: async p => { await p.hover('#histTok rect[data-i="24"]'); } });
  await shot(b, { name: 'panel-machines', hash: 'maquinas', h: 860, act: async p => { await p.click('#btnCode'); await p.waitForSelector('.codebox'); await p.waitForTimeout(600); await p.evaluate(() => scrollTo(0, 0)) } });
  await shot(b, { name: 'panel-about', hash: 'sobre' });
  await shot(b, { name: 'panel-light', theme: 'light' });
  await shot(b, { name: 'panel-mobile', w: 390, h: 844, dpr: 2 });
  await b.close();
})();

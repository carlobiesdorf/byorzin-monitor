// grava o roteiro de uso do painel como quadros PNG + durations.json (vira GIF em Python)
const { chromium } = require('playwright-core');
const { install } = require('./mock.js');
const fs = require('fs');
const exe = process.env.CHROMIUM || (process.env.HOME + '/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell');
const B = process.env.PANEL || 'http://127.0.0.1:47873', OUT = process.argv[2];
let n = 0; const durs = [];
(async () => {
  const b = await chromium.launch({ executablePath: exe });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const p = await ctx.newPage();
  p.on('pageerror', e => console.log('ERR', e.message));
  p.on('dialog', d => d.accept());
  await p.addInitScript(() => {
    localStorage.setItem('byorzin.lang', 'en'); localStorage.setItem('byorzin.theme', 'dark');
    addEventListener('DOMContentLoaded', () => {
      const c = document.createElement('div'); c.id = '__cur';
      c.style.cssText = 'position:fixed;z-index:99999;left:0;top:0;width:22px;height:22px;pointer-events:none;transform:translate(-3px,-2px)';
      c.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M3 2l7 19 2.6-7.4L20 11z" fill="#fff" stroke="#000" stroke-width="1.4" stroke-linejoin="round"/></svg>';
      document.body.appendChild(c);
      addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px' }, true);
    });
  });
  await install(p, B, 'en');
  await p.goto(B + '/?lang=en#tela'); await p.waitForTimeout(2500);
  let mx = 720, my = 450; await p.mouse.move(mx, my);
  const snap = async ms => { const f = OUT + '/f' + String(n++).padStart(4, '0') + '.png'; await p.screenshot({ path: f }); durs.push(ms) };
  const hold = async ms => snap(ms);
  const burst = async (ms, step = 90) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { await snap(step) } };
  const moveTo = async (sel, steps = 8) => {
    const bb = await (await p.$(sel)).boundingBox(); const tx = bb.x + bb.width / 2, ty = bb.y + bb.height / 2;
    for (let i = 1; i <= steps; i++) { await p.mouse.move(mx + (tx - mx) * i / steps, my + (ty - my) * i / steps); await snap(60) }
    mx = tx; my = ty;
  };
  const click = async (sel, after = 900) => { await moveTo(sel); await p.click(sel); await burst(after) };

  await hold(1600);                                   // Visão geral
  await click('.srow', 700); await hold(1700);        // gaveta da sessão
  await p.keyboard.press('Escape'); await burst(300);
  await click('#tabs button[data-t=layouts]', 1500); await hold(900);
  await click('#lgrid .gi:nth-child(6) [data-act=use]', 600); await hold(1500);   // "Use" o Palco
  await click('#tabs button[data-t=maquinas]', 500); await hold(700);
  await click('#btnCode', 900); await hold(1700);
  await click('#themeBtn', 400); await hold(1800);    // tema claro
  fs.writeFileSync(OUT + '/durations.json', JSON.stringify(durs));
  console.log('frames', n, 'total ms', durs.reduce((a, b) => a + b, 0));
  await b.close();
})();

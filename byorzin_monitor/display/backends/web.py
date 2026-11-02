# Tela no navegador: a página /tela do painel mostra o Byorzin em tela cheia em qualquer coisa
# com navegador (tablet, celular, segundo monitor, TV, Raspberry Pi em modo quiosque).
# O painel desenha os quadros com o mesmo Renderer da tela USB, então funciona mesmo quando a
# tela USB está em outra máquina. Um cache garante 1 desenho por quadro, não importa quantos
# navegadores estejam olhando.
#
# Rotas (servidas pelo painel):
#   /tela                 página em tela cheia (aceita ?layout=nome, ?fps=n e ?maxscale=1..4)
#   /tela/frame.jpg       quadro atual (JPEG); a página busca em sequência (~4 fps)
#   /tela/stream.mjpg     o mesmo como MJPEG contínuo (VLC, Home Assistant, <img> simples);
#                         no máximo MAX_STREAMS ao mesmo tempo, cada um por até STREAM_MAX_SECONDS
# Alta resolução: frame.jpg e stream.mjpg aceitam ?scale=1..4 (quadro 480K x 320K, desenhado
# nativamente maior, não ampliado) ou ?w=largura desejada em pixels (K = ceil(w/480)). Padrão 1.
# A página escolhe K pela área visível × devicePixelRatio, com teto PAGE_MAX_SCALE.
# De outro aparelho, abra uma vez o link com a chave do painel (/tela?key=...); ver panel/auth.py.
import io
import math
import threading
import time

from byorzin_monitor.settings import LAYOUT_NAMES

MAX_FPS = 8
JPEG_QUALITY = 90
PAGE_MAX_SCALE = 3              # teto padrão da página (K=3 = 1440x960); ?maxscale=4 libera 1920x1280
BOUNDARY = "byorzinframe"
MAX_STREAMS = 4                 # clientes MJPEG simultâneos
STREAM_MAX_SECONDS = 2 * 3600   # depois disso o stream fecha (o cliente reconecta se quiser)
_streams = threading.BoundedSemaphore(MAX_STREAMS)


class TelaHub:
    def __init__(self, cfg, settings, fetcher, draw_lock=None):
        self.cfg, self.settings, self.fetcher = cfg, settings, fetcher
        self.draw_lock = draw_lock or threading.Lock()   # as cenas usam estado global (cores)
        self.lock = threading.Lock()
        self.renderers = {}      # layout (ou None) -> Renderer: cada um com o seu Director
        self.cache = {}          # layout (escala 1) ou (layout, escala) -> (instante, jpeg)

    def interval(self):
        return 1 / max(1, min(MAX_FPS, int(self.settings.get().get("fps", 5))))

    def frame(self, layout=None, scale=1):
        """(instante, bytes JPEG) do quadro atual na escala pedida; redesenha só se o do cache já
        venceu (um desenho por escala por quadro, não importa quantos navegadores olham)."""
        from byorzin_monitor.display.scenes import clamp_scale
        layout = layout if layout in LAYOUT_NAMES else None
        scale = clamp_scale(scale)
        key = layout if scale == 1 else (layout, scale)
        with self.lock:
            now = time.time()
            t, jpg = self.cache.get(key, (0, None))
            if jpg is not None and now - t < self.interval():
                return t, jpg
            r = self.renderers.get(layout)
            if r is None:
                from byorzin_monitor.display.engine import Renderer
                r = self.renderers[layout] = Renderer(self.cfg, self.settings, self.fetcher, layout=layout)
            with self.draw_lock:
                img = r.frame(now, scale=scale)
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=JPEG_QUALITY)
            self.cache[key] = (now, buf.getvalue())
            return self.cache[key]


def hub_for(panel):
    """Hub único do processo do painel, criado no primeiro acesso a /tela."""
    hub = getattr(panel, "_tela_hub", None)
    if hub is None:
        hub = panel._tela_hub = TelaHub(panel.cfg, panel.settings, panel.fetcher, panel.lock)
    return hub


def scale_from(query):
    """Escala pedida na URL: ?scale=1..4 ou ?w=largura em px (K = ceil(w/480)); padrão 1."""
    from byorzin_monitor.display.scenes import W, clamp_scale
    sc = (query.get("scale") or [None])[0]
    if sc is not None:
        return clamp_scale(sc)
    w = (query.get("w") or [None])[0]
    try:
        w = float(w)
    except (TypeError, ValueError):
        return 1
    return clamp_scale(math.ceil(w / W)) if math.isfinite(w) and w > 0 else 1


def handle(h, path, query, hub):
    """Atende as rotas /tela* no BaseHTTPRequestHandler `h`. Devolve False se a rota não é daqui."""
    layout = (query.get("layout") or [None])[0]
    scale = scale_from(query)
    if path in ("/tela", "/tela/"):
        if hasattr(h, "send_page"):
            h.send_page(PAGE, frame=True)      # CSP com nonce; pode ir num iframe (Home Assistant)
        else:
            h.send(200, PAGE, "text/html; charset=utf-8")
        return True
    if path == "/tela/frame.jpg":
        _, jpg = hub.frame(layout, scale)
        h.send(200, jpg, "image/jpeg")
        return True
    if path == "/tela/stream.mjpg":
        if not _streams.acquire(blocking=False):
            h.send(503, {"erro": f"no máximo {MAX_STREAMS} streams ao mesmo tempo; use /tela/frame.jpg"})
            return True
        try:
            _stream(h, hub, layout, scale)
        finally:
            _streams.release()
        return True
    return False


def _stream(h, hub, layout, scale=1):
    h.send_response(200)
    h.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
    h.send_header("Cache-Control", "no-store")
    h.send_header("Connection", "close")
    h.end_headers()
    last = None
    h.close_connection = True
    end = time.time() + STREAM_MAX_SECONDS
    try:
        h.connection.settimeout(15)          # cliente que parou de ler não segura a thread
        while time.time() < end:
            t, jpg = hub.frame(layout, scale)
            if t != last:
                h.wfile.write(f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpg)}\r\n\r\n".encode()
                              + jpg + b"\r\n")
                h.wfile.flush()
                last = t
            time.sleep(hub.interval())
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass                      # o navegador fechou a conexão (ou parou de ler)


PAGE_TEMPLATE = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#000000">
<title>Byorzin</title>
<link rel="icon" href="/img/icon.png">
<style>
html,body{margin:0;height:100%;background:#000;overflow:hidden}
body.idle{cursor:none}
#f{position:fixed;inset:0;width:100%;height:100%;object-fit:contain;display:block;image-rendering:auto}
#fs{position:fixed;right:14px;bottom:14px;width:44px;height:44px;border-radius:50%;border:1px solid #333;
background:rgba(20,24,36,.7);color:#ccc;font-size:20px;cursor:pointer;opacity:.55;transition:opacity .4s}
body.idle #fs{opacity:0;pointer-events:none}
#st{position:fixed;left:14px;bottom:14px;color:#777;font:13px system-ui,sans-serif}
</style>
</head>
<body>
<img id="f" alt="Byorzin">
<button id="fs" title="Tela cheia (ou dois cliques na imagem)">&#x26F6;</button>
<div id="st">conectando…</div>
<script>
const q=new URLSearchParams(location.search),lay=q.get('layout')||'';
const base=location.pathname.replace(/\\/+$/,'');
const url=base+'/frame.jpg?'+(lay?'layout='+encodeURIComponent(lay)+'&':'');
const gap=1000/Math.min(8,Math.max(1,+q.get('fps')||4));
/* alta resolução: K = pixels físicos da área útil / 480x320 (arredonda para cima), teto maxscale */
const maxK=Math.min(4,Math.max(1,Math.floor(+q.get('maxscale')||PAGE_MAX_SCALE)));
let K=1;
function pickK(){const r=window.devicePixelRatio||1;
  const need=Math.min(innerWidth*r/480,innerHeight*r/320);
  K=Math.min(maxK,Math.max(1,Math.ceil(need-0.05)))}
pickK();let rz;addEventListener('resize',()=>{clearTimeout(rz);rz=setTimeout(pickK,250)});
const img=document.getElementById('f'),st=document.getElementById('st');
let fails=0,cur=null;
async function tick(){
  const t0=performance.now();
  if(!document.hidden){
    try{
      const r=await fetch(url+'scale='+K+'&t='+Date.now(),{cache:'no-store'});
      if(!r.ok)throw r.status;
      const u=URL.createObjectURL(await r.blob());
      await new Promise((ok,ko)=>{img.onload=ok;img.onerror=ko;img.src=u});
      if(cur)URL.revokeObjectURL(cur);cur=u;fails=0;st.textContent='';
    }catch(e){if(++fails>2)st.textContent='sem conexão com o painel… tentando de novo'}
  }
  setTimeout(tick,Math.max(0,(fails||document.hidden?1500:gap)-(performance.now()-t0)));
}
tick();
/* tela cheia */
function fs(){const d=document,e=d.documentElement;
  if(d.fullscreenElement||d.webkitFullscreenElement)(d.exitFullscreen||d.webkitExitFullscreen).call(d);
  else(e.requestFullscreen||e.webkitRequestFullscreen||(()=>{})).call(e)}
document.getElementById('fs').onclick=fs;img.ondblclick=fs;
/* botão e cursor somem sem movimento */
let hide;function wake(){document.body.classList.remove('idle');clearTimeout(hide);
  hide=setTimeout(()=>document.body.classList.add('idle'),3000)}
for(const ev of['mousemove','touchstart','keydown'])addEventListener(ev,wake,{passive:true});wake();
/* mantém a tela acesa (Wake Lock: só em HTTPS ou localhost) */
async function keepAwake(){try{if('wakeLock' in navigator&&document.visibilityState==='visible')
  await navigator.wakeLock.request('screen')}catch(e){}}
document.addEventListener('visibilitychange',keepAwake);keepAwake();
</script>
</body>
</html>
"""
PAGE = PAGE_TEMPLATE.replace("PAGE_MAX_SCALE", str(PAGE_MAX_SCALE))

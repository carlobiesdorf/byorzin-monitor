# Registro das telas suportadas e detecção automática.
#
# Para adicionar uma tela: crie um módulo aqui com uma classe que herda de `base.Backend`,
# registre em BACKENDS e, se for USB, acrescente o identificador em KNOWN_USB.
import importlib
import os

# nome -> (módulo, classe)
BACKENDS = {
    "turing-a": ("byorzin_monitor.display.backends.turing_a", "TuringA"),
    "turing-b": ("byorzin_monitor.display.backends.turing_b", "TuringB"),            # experimental
    "weact": ("byorzin_monitor.display.backends.weact", "WeAct"),                    # experimental
    "weact-096": ("byorzin_monitor.display.backends.weact", "WeActMini"),            # experimental
    "terminal": ("byorzin_monitor.display.backends.terminal", "Terminal"),
    "framebuffer": ("byorzin_monitor.display.backends.framebuffer", "Framebuffer"),
    "sim": ("byorzin_monitor.display.backends.sim", "Sim"),
}
# "web" não abre nada aqui: a página /tela é servida pelo painel (ver backends/web.py)

# telas USB conhecidas: (vid, pid, número de série, backend, descrição). O número de série é um
# trecho que deve aparecer nele, "^xx" = começa com xx, ou None. A ordem importa: vale o 1º que casar.
KNOWN_USB = [
    (0x1A86, 0x5722, "USB35INCHIPSV2", "turing-a", 'Turing Smart Screen 3.5" (rev A)'),
    (0x1A86, 0x5722, "2017-2-25", "turing-b", 'XuanFang 3.5" (rev B) [experimental]'),
    (0x1A86, 0xFE0C, "^AD", "weact-096", 'WeAct Studio Display FS 0.96" [experimental]'),
    (0x1A86, 0xFE0C, None, "weact", 'WeAct Studio Display FS 3.5" [experimental]'),
]


def serial_matches(part, serial):
    if not part:
        return True
    serial = serial or ""
    return serial.startswith(part[1:]) if part.startswith("^") else part in serial

# link criado pela regra udev do byorzin-monitor para a tela encontrada
UDEV_LINK = "/dev/ttyByorzin"


def detect():
    """Lista as telas encontradas: [{"backend", "device", "label"}]."""
    found = []
    try:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
    except Exception:
        ports = []
    for p in ports:
        for vid, pid, serial_part, backend, label in KNOWN_USB:
            if p.vid == vid and p.pid == pid and serial_matches(serial_part, p.serial_number):
                found.append({"backend": backend, "device": p.device, "label": label})
                break
    return found


def available(panel_url=None):
    """Todas as saídas possíveis nesta máquina, com e sem hardware, para o doctor e o painel:
    [{"backend", "device", "label", "kind"}], kind = usb | web | terminal | framebuffer."""
    out = [{**d, "kind": "usb"} for d in detect()]
    out.append({"backend": "web", "device": f"{panel_url}/tela" if panel_url else "/tela",
                "label": "navegador (página /tela do painel)", "kind": "web"})
    out.append({"backend": "terminal", "device": "", "label": "terminal (byorzin-monitor display --backend terminal)",
                "kind": "terminal"})
    try:
        from byorzin_monitor.display.backends.framebuffer import list_framebuffers
        fbs = list_framebuffers()
    except Exception:
        fbs = []
    for fb in fbs:
        w, h = fb["size"]
        out.append({"backend": "framebuffer", "device": fb["device"], "kind": "framebuffer",
                    "label": f"framebuffer {fb['name'] or fb['device']} {w}x{h} {fb['bpp']} bpp"})
    return out


def open_backend(name="auto", device="", **opts):
    """Abre a tela pedida; "auto" usa a primeira detectada."""
    if name in ("", "auto", None):
        found = detect()
        if not found:
            raise RuntimeError("nenhuma tela USB conhecida encontrada. Plugue a tela, ou escolha outra saída: "
                               "--backend terminal, --backend framebuffer --device /dev/fbN, --png quadro.png, "
                               "ou a página /tela do painel (veja `byorzin-monitor display --help` e `doctor`)")
        name, device = found[0]["backend"], device or found[0]["device"]
    if name not in BACKENDS:
        raise RuntimeError(f"tela desconhecida: {name} (opções: auto, {', '.join(BACKENDS)}, web)")
    usb = {k[3] for k in KNOWN_USB}
    if not device and name in usb and os.path.exists(UDEV_LINK):
        device = UDEV_LINK
    mod, cls = BACKENDS[name]
    try:
        return getattr(importlib.import_module(mod), cls)(device=device, **opts)
    except Exception as e:
        if type(e).__name__ == "SerialException":      # pyserial: porta inexistente/ocupada
            raise RuntimeError(f"não consegui abrir a tela {name} ({device or 'porta padrão'}): {e}. "
                               "Ela está plugada? Veja `byorzin-monitor doctor`.") from None
        raise

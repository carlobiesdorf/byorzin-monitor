# Telas suportadas

O Byorzin desenha sempre um quadro lógico de 480×320. Cada *backend* sabe levar esse quadro para
um tipo de saída; se a saída tiver outro tamanho, o quadro é escalado mantendo a proporção (com
bordas pretas) e girado 90° quando a saída é retrato.

| Backend | Tela | Como conecta | Status |
|---|---|---|---|
| `turing-a` | Turing Smart Screen 3.5" (rev A) | serial USB `1a86:5722`, série `USB35INCHIPSV2` | **testado** |
| `turing-b` | XuanFang 3.5" (rev B / "flagship") | serial USB `1a86:5722`, série `2017-2-25` | experimental |
| `weact` | WeAct Studio Display FS 3.5" | serial USB `1a86:fe0c` | experimental |
| `weact-096` | WeAct Studio Display FS 0.96" | serial USB `1a86:fe0c`, série começando com `AD` | experimental |
| `web` | qualquer navegador: tablet, celular, segundo monitor, TV, Raspberry Pi em modo quiosque | página `/tela` do painel | **testado** |
| `terminal` | um terminal ou painel do tmux | caracteres `▀` em truecolor | **testado** |
| `framebuffer` | telas SPI do Raspberry Pi, HDMI sem desktop | `/dev/fbN` | testado com arquivo simulado |
| `sim` | nenhuma (testes) | grava PNG | **testado** |

**Experimental** = escrito a partir da documentação pública do protocolo (código próprio, MIT), com
testes automatizados da codificação, mas **sem teste em hardware real**. Se você tem uma dessas
telas, rode `byorzin-monitor display --backend <nome>` e conte como foi (abra uma issue).

`byorzin-monitor doctor` lista as telas USB conectadas e as outras saídas disponíveis na máquina;
o painel mostra a mesma lista na aba **Tela**.

## Tela USB

Com `backend = "auto"` (padrão do `config.toml`), o display usa a primeira tela conhecida que
encontrar. A regra udev instalada pelo `byorzin-monitor setup` cria `/dev/ttyByorzin` e sobe o
serviço da tela ao plugar. Para forçar um modelo:

```toml
# ~/.config/byorzin-monitor/config.toml
backend = "weact"
device = "/dev/ttyACM0"
```

ou na linha de comando: `byorzin-monitor display --backend turing-b --device /dev/ttyACM0`.

## Navegador (`web`)

O painel serve a página **`http://<máquina>:8788/tela`**: o Byorzin em tela cheia, fundo preto,
mantendo a proporção. Funciona mesmo se a tela USB estiver em outra máquina, porque o painel
desenha os quadros por conta própria (um desenho por quadro, não importa quantos navegadores estejam
abertos). Na aba **Tela** do painel há o link "Abrir tela no navegador".

- `?layout=lista` fixa um layout só nesta página (os outros seguem o painel);
- `?fps=2` deixa mais leve (padrão 4, máximo 8);
- dois cliques na imagem ou o botão no canto alternam a tela cheia; botão e cursor somem sozinhos;
- a página pede ao navegador para não apagar a tela (Wake Lock). Navegadores só permitem isso em
  HTTPS ou `localhost`; numa rede local em HTTP, desligue a proteção de tela do aparelho;
- `/tela/frame.jpg` devolve o quadro atual e `/tela/stream.mjpg` um fluxo MJPEG contínuo (VLC,
  Home Assistant, ou um `<img>` comum).

**Alta resolução.** A página desenha o quadro nativamente maior (não amplia a imagem de 480x320):
os layouts continuam pensando em 480x320, mas o canvas nasce K vezes maior, as fontes vêm em K× o
tamanho e o Byorzin é rasterizado do SVG já no tamanho final. A página escolhe K pela área visível
× `devicePixelRatio` (arredonda para cima) e recalcula ao redimensionar. Teto padrão **K=3**
(1440x960, nítido num monitor Full HD); `?maxscale=4` libera 1920x1280 e `?maxscale=1` volta ao
quadro pequeno (aparelhos fracos).

- `/tela/frame.jpg?scale=1..4` e `/tela/stream.mjpg?scale=1..4` pedem a escala direto; `?w=1920`
  pede pela largura (K = ceil(w/480), máximo 4). Sem parâmetro: 480x320, como antes. JPEG qualidade 90;
- o painel guarda um desenho por escala por quadro: vários navegadores na mesma escala não custam mais;
- as prévias do painel também aceitam `?scale=`: `/img/layout/<nome>.png?scale=2`,
  `/img/scene/<nome>.png?scale=2` (padrão 1);
- a tela USB, o terminal e o framebuffer continuam sempre em K=1, byte a byte iguais
  (`tests/test_hd.py` confere).

Custo medido (desktop, cache de sprites quente; layout `cards`, o mais pesado): desenho + JPEG
≈ 14 ms / 40 KB em K=1, 20 ms / 100 KB em K=2, 33 ms / 175 KB em K=3, 46 ms / 250 KB em K=4.
A 4 fps isso cabe folgado; a primeira vez que um Byorzin grande aparece numa escala nova o SVG é
rasterizado (≈0,4 s em K=3 e ≈0,6 s em K=4 para o Byorzin de 300 px das cenas ociosas) e depois
fica em cache (até 96 MB de sprites em alta resolução). Num Raspberry Pi, prefira `?maxscale=2`.

**De outro aparelho é preciso a chave do painel** (ver `SECURITY.md`). Pegue o link pronto na
máquina do painel com `byorzin-monitor panel-url` (ou no painel: **Máquinas** → *Acesso de outro
aparelho*, link "só a tela"). Ele tem a forma `http://192.168.1.10:8788/tela?key=SUA_CHAVE`: na
primeira abertura o painel grava um cookie e tira a chave da barra de endereço. Para VLC/Home
Assistant, use `.../tela/stream.mjpg?key=SUA_CHAVE` (eles não guardam cookie). Gerar uma chave
nova no painel invalida os links antigos.

### Raspberry Pi em modo quiosque

Com Raspberry Pi OS com desktop, aponte o Chromium para a página do painel (pode estar em outra
máquina da rede):

```bash
chromium-browser --kiosk --noerrdialogs --disable-infobars --incognito \
  --check-for-update-interval=31536000 "http://192.168.1.10:8788/tela?key=SUA_CHAVE"
```

Com `--incognito` o cookie não fica guardado, por isso a URL leva a chave (`?key=`): ela é
validada a cada abertura. Para abrir sozinho ao ligar, crie `~/.config/autostart/byorzin.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=Byorzin
Exec=chromium-browser --kiosk --noerrdialogs --disable-infobars --incognito "http://192.168.1.10:8788/tela?key=SUA_CHAVE"
```

e desative a proteção de tela (`sudo raspi-config` → Display Options → Screen Blanking → Não).
Sem desktop, prefira o backend `framebuffer` (abaixo).

## Terminal

```bash
byorzin-monitor display --backend terminal            # usa o terminal inteiro
byorzin-monitor display --backend terminal --layout lista
```

Cada caractere mostra dois pixels (`▀` com cor de texto e de fundo), em truecolor — funciona em
quase todos os terminais modernos (GNOME Terminal, Konsole, kitty, WezTerm, iTerm2, Windows
Terminal, tmux com `set -g default-terminal "tmux-256color"` e `set -as terminal-features ",*:RGB"`).
O desenho acompanha o tamanho do terminal, só redesenha o que mudou e devolve o terminal como
estava ao sair com Ctrl+C. Quanto maior o terminal (ou menor a fonte), mais nítido.

## Framebuffer (`/dev/fbN`)

Para telas SPI do Raspberry Pi (com driver fbtft/fb) ou HDMI sem desktop:

```bash
byorzin-monitor display --backend framebuffer --device /dev/fb1
```

Com sessão gráfica aberta (X11/Wayland), o `/dev/fb0` é do desktop: use a página `/tela` ou o
terminal (o `doctor` só sugere framebuffer quando não há `DISPLAY`/`WAYLAND_DISPLAY`).

Resolução, bits por pixel e bytes por linha são lidos de `/sys/class/graphics/fbN/`. Suporta 16 bpp
(RGB565), 24 bpp (BGR) e 32 bpp (BGRA). O usuário precisa estar no grupo `video`
(`sudo usermod -aG video $USER`). No HDMI com console de texto, esconda o cursor piscando com
`sudo sh -c 'setterm --cursor off > /dev/tty1'` e desligue o apagamento com `consoleblank=0` no
`cmdline.txt`.

### Testar sem hardware (arquivo no lugar do `/dev/fbN`)

Um arquivo comum também serve, informando o tamanho e os bits por pixel (o arquivo é criado ou
aumentado até `largura × altura × bpp/8` bytes):

```bash
byorzin-monitor display --backend framebuffer --device /tmp/fb.raw --size 480x320 --bpp 16
# em outro terminal, converta o conteúdo para PNG e confira:
python3 -c "import numpy as n; from PIL import Image; a=n.fromfile('/tmp/fb.raw','<u2').reshape(320,480); \
Image.fromarray(n.dstack([(a>>11<<3),(a>>5&63)<<2,(a&31)<<3]).astype('u1')).save('/tmp/fb.png')"
```

Sem `--size`, um caminho que não é `/dev/fbN` dá erro explicando isso.

## Simulada (`sim`)

Para testes, sem hardware:

```bash
byorzin-monitor display --backend sim --device /tmp/byorzin.png    # sobrescreve sempre o mesmo PNG
byorzin-monitor display --backend sim --device /tmp/quadros/       # um PNG por quadro (até 500)
byorzin-monitor display --png /tmp/agora.png                       # só o quadro atual e sai
```

## Opções e erros comuns

`byorzin-monitor display --help` lista as telas (`--backend`), os layouts e as opções. Erros esperados
saem numa linha só (`byorzin-monitor: erro: ...`) com código de saída 1, sem traceback:

- `auto` sem tela USB conhecida: sugere `--backend terminal`, framebuffer, `--png` ou a página `/tela`;
- tela desconhecida, layout desconhecido ou opção errada (ex.: `--pgn`): mostra as opções válidas;
- porta serial ausente/ocupada (`turing-a` sem a tela plugada) ou sem permissão (grupo `dialout`/`video`);
- porta do coletor ou do painel já em uso.

Para ver o traceback completo, rode com `BYORZIN_DEBUG=1`.

Ao abrir, a tela nunca começa pela cena "limite" (uso ≥ 90%); com `--layout` (ou `/tela?layout=`) o
layout pedido aparece sempre, sem o alerta de limite por cima. Emoji em títulos e nomes de projeto
são retirados no desenho (a fonte DejaVu não tem esses desenhos e eles virariam "□"); acentos ficam.

## O que ainda falta

- **Turing rev C (2.1", 5", 8.8")**: não implementado. O protocolo público é de engenharia reversa
  e tem partes sem explicação: a tela troca de identificação USB ao acordar (`1a86:ca21` →
  `0525:a4a7`/`1d6b:0121`), os pacotes são blocos de 250 bytes com um byte extra a cada 249, há dois
  bytes no comando de imagem cheia cujo significado ninguém documentou, as respostas de 1024 bytes
  nunca são interpretadas e o formato de cor (BGR ou BGRA) depende da versão da ROM. Precisa de
  alguém com o hardware para validar antes de escrevermos um driver.
- **Turing USB novos (VID `1cbe`, 2.8" a 12.3")**: outro protocolo (USB bulk com comandos cifrados
  e quadros JPEG/PNG). Não implementado.
- **WeAct**: a documentação diverge sobre a orientação. Usamos a rotação do firmware
  (`02 02 0A` = paisagem, coordenadas já giradas). Se a imagem sair torta, a alternativa é mandar
  orientação 0 e girar no computador — conte na issue.
- **XuanFang rev B**: as sub-revisões antigas (A01/A02) só ligam e desligam o brilho; os LEDs da
  versão "flagship" ainda não são usados.
- Layouts responsivos (hoje tudo é 480×320 escalado) e ESP32 "Cheap Yellow Display".

## Como adicionar uma tela nova

1. Crie `byorzin_monitor/display/backends/<nome>.py` com uma classe que herda de `base.Backend`:
   - `name`, `label`, `size` (largura × altura em que você quer receber as imagens);
   - `show(img, full=False)`: recebe uma imagem PIL já em `size` e devolve quantos pixels enviou
     (dica: guarde o quadro anterior e mande só o que mudou);
   - `set_brightness(pct)`, `on()`, `off()` e `close()` se a tela suportar;
   - aceite `device=""` e, para testes, um `ser=` com uma porta serial falsa;
   - se não foi testada em hardware, `experimental = True` e "[experimental]" no `label`.
2. Registre em `BACKENDS` (`backends/__init__.py`). Se for USB, acrescente `(vid, pid, série, nome,
   descrição)` em `KNOWN_USB`: a detecção automática, o `doctor` e a regra udev passam a conhecê-la.
3. Escreva um teste em `tests/` que verifique os bytes enviados (veja `tests/test_usb_extra.py`).
4. Use só código próprio: fatos de protocolo podem vir de qualquer lugar, código de projetos GPL não.
5. Atualize a tabela no topo deste arquivo.

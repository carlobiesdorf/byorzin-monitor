# quadros PNG + durations.json (gravados por rec.js) -> GIF otimizado: python togif.py <pasta> <saida.gif> <largura> <cores: 256 = paleta por quadro> [saida.webp]
import json, sys
from pathlib import Path
from PIL import Image
d = Path(sys.argv[1]); out = sys.argv[2]; width = int(sys.argv[3]); colors = int(sys.argv[4])
durs = json.load(open(d / 'durations.json'))
fr = [Image.open(d / f'f{i:04d}.png').convert('RGB') for i in range(len(durs))]
fr = [f.resize((width, round(f.height * width / f.width)), Image.LANCZOS) for f in fr]
pick = fr[::max(1, len(fr) // 10)]
fw, fh = fr[0].width // 2, fr[0].height // 2
sample = Image.new('RGB', (fw, fh * len(pick)))
for i, f in enumerate(pick): sample.paste(f.resize((fw, fh)), (0, fh * i))
pal = sample.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in fr] if colors < 256 else \
    [f.quantize(colors=255, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE) for f in fr]  # paleta por quadro
o, du = [], []
for f, ms in zip(q, durs):
    if o and f.tobytes() == o[-1].tobytes(): du[-1] += ms
    else: o.append(f); du.append(ms)
o[0].save(out, save_all=True, append_images=o[1:], duration=du, loop=0, optimize=True, disposal=1)
print(len(o), 'frames', sum(du), 'ms', Path(out).stat().st_size // 1024, 'KB')
if len(sys.argv) > 5:   # webp animado com as mesmas durações
    fr[0].save(sys.argv[5], save_all=True, append_images=fr[1:], duration=durs, loop=0, quality=80, method=4)
    print('webp', Path(sys.argv[5]).stat().st_size // 1024, 'KB')

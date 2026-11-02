# Turing Smart Screen 3.5" — protocolo "revision A"

Dispositivo testado em hardware real em 02/11/2026 (Linux, driver `cdc_acm`).

## Identificação
- USB `1a86:5722` (QinHeng), driver `cdc_acm` → `/dev/ttyACM*`
- udev: `ID_VENDOR=Turing`, `ID_MODEL=UsbMonitor`, `ID_SERIAL=Turing_UsbMonitor_USB35INCHIPSV2`
- Caminho estável: `/dev/serial/by-id/usb-Turing_UsbMonitor_USB35INCHIPSV2-if00`
- Permissão: grupo `dialout`
- Serial: 115200 baud, `rtscts=True`, timeout 1 s
- `HELLO` (69) **não responde** neste modelo — não usar para detectar; detectar pelo udev.

## Comando (6 bytes)
```
b0 = x >> 2
b1 = ((x & 3) << 6) + (y >> 4)
b2 = ((y & 15) << 4) + (ex >> 6)
b3 = ((ex & 63) << 2) + (ey >> 8)
b4 = ey & 255
b5 = comando
```

| Comando | Código | Parâmetros |
|---|---|---|
| HELLO | 69 | — |
| RESET | 101 | — |
| CLEAR | 102 | — |
| TO_BLACK | 103 | — |
| SCREEN_OFF | 108 | — |
| SCREEN_ON | 109 | — |
| SET_BRIGHTNESS | 110 | `x = 255 - nivel%*2.55` (0 = máximo) |
| SET_ORIENTATION | 121 | +10 bytes: `orientação+100, 320>>8, 320&255, 480>>8, 480&255, 0×5` (paisagem = 2) |
| DISPLAY_BITMAP | 197 | `x,y,ex,ey` (inclusivos) seguido de `w*h*2` bytes RGB565 little-endian, enviados em blocos de `w*8` bytes |

## Medições (Python puro, sem numpy)
- Tela cheia 480×320: **2,45 s**
- Recorte 90×110: **~0,17 s**
- Conclusão: atualizar só áreas alteradas; tela cheia apenas na troca de modo.

# Interface comum das telas. Um backend recebe imagens PIL já no tamanho dele (`size`)
# e cuida de enviá-las ao hardware (ou navegador, terminal...).


class Backend:
    name = "base"
    label = "tela genérica"
    size = (480, 320)          # largura x altura em pixels
    partial = True             # True = só manda o que mudou (show decide); False = sempre a imagem inteira
    experimental = False       # True = feito a partir da documentação do protocolo, sem teste em hardware
    save_frame = True          # o display grava frame.png (o painel mostra "o que está na tela agora")
    quiet = False              # True = o display não escreve no stderr (ex.: desenhando no próprio terminal)

    def show(self, img, full=False):
        """Mostra a imagem. Devolve quantos pixels foram enviados (para estatística)."""
        raise NotImplementedError

    def set_brightness(self, pct):
        pass

    def on(self):
        pass

    def off(self):
        pass

    def close(self):
        pass

<p align="center">
  <img src="docs/img/icon.png" alt="Byorzin, o robô mascote" width="96">
</p>

<h1 align="center">Byorzin Monitor</h1>

<p align="center">
  <strong>Todas as sessões e subagentes do Claude Code, de todos os seus computadores, numa tela só.</strong><br>
  Vários computadores, várias contas do Claude, uma tela: um display USB ou qualquer navegador.
</p>

<p align="center">
  <a href="https://github.com/carlobiesdorf/byorzin-monitor/actions/workflows/ci.yml"><img src="https://github.com/carlobiesdorf/byorzin-monitor/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-39ff88" alt="Licença: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-3776ab" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/platform-Linux-555" alt="Plataforma: Linux">
</p>

<p align="center">
  <a href="README.md">English</a> · <b>Português (Brasil)</b>
</p>

<p align="center">
  <img src="docs/img/hero.png" alt="Byorzin Monitor: uma tela USB de 3,5 polegadas mostrando quatro sessões do Claude Code como robozinhos, ao lado do painel web" width="900">
</p>

Cada computador onde você usa o Claude Code roda um pequeno **coletor**. Uma **tela** mostra as
sessões e os subagentes de todos eles, cada um como um **Byorzin**, um robozinho que trabalha,
chama subagentes, levanta a mão quando está **esperando você**, comemora quando uma tarefa longa
termina e dorme (sonhando com as suas estatísticas) quando ninguém está usando.

> **Sem tela USB? Sem problema.** Abra `http://localhost:8788/tela` em qualquer navegador: os mesmos
> layouts, desenhados em alta resolução, num monitor, TV, tablet ou celular.

> As imagens estão em inglês; o painel e a tela também falam português (ajuste *Idioma*).

## Por quê

- **Vários computadores, várias contas do Claude, uma tela.** Desktop, notebook e servidor (cada
  um na sua conta do Claude, se quiser) aparecem juntos. Pareie as máquinas com um código de 6 dígitos.
- **Entende de longe.** Trabalhando, pensando, esperando você, erro, limite atingido, dormindo:
  dá para ver do outro lado da sala qual sessão precisa de você.
- **Qualquer tela.** Um display USB barato de 3,5", qualquer navegador (`/tela`), um painel de
  terminal ou o framebuffer do Linux.
- **Privacidade em primeiro lugar.** Só metadados (nomes de eventos, ferramentas, tipos de agente,
  contagem de tokens). Nunca prompts, comandos, conteúdo de arquivos ou respostas. Nada sai da sua rede.
- **Plug and play.** Um comando `setup`; plugou a tela USB, ela começa a desenhar.

## Começo rápido

Requisitos: Linux, Python 3.11+, Claude Code, e Cairo + fontes DejaVu
(`sudo apt install libcairo2 fonts-dejavu-core` no Debian/Ubuntu).

**1. Instale**

```bash
pipx install git+https://github.com/carlobiesdorf/byorzin-monitor
```

ou a partir de um clone (cria a `.venv` e já roda o `setup`, então pule o passo 2):

```bash
git clone https://github.com/carlobiesdorf/byorzin-monitor && cd byorzin-monitor && ./install.sh
```

**2. Configure este computador**

```bash
byorzin-monitor setup
```

Ele sobe o coletor (porta 8787) e o painel (porta 8788) como serviços systemd do usuário e
adiciona os hooks do Claude Code (mostra a mudança no `~/.claude/settings.json` e pergunta antes).
Pede sudo uma vez para a parte de sistema (permissões da tela USB, regra udev, firewall): com uma
tela suportada, ela liga sozinha sempre que você plugar. Sem tela, o mesmo setup deixa o painel e a
`/tela` prontos. Use `--no-sudo` para pular os passos com sudo.

**3. Abra o painel**

Acesse **http://localhost:8788** neste computador, ou **http://localhost:8788/tela** para a tela
no navegador. Para o celular ou outro PC, pegue o link com `byorzin-monitor panel-url` (ou painel →
**Máquinas** → *Acesso de outro aparelho*). Sessões que já estavam abertas começam a aparecer
quando o Claude Code recarrega as configurações.

Algo não funcionou? `byorzin-monitor doctor` confere serviços, tela, hooks, portas e máquinas.

## Adicione mais computadores

1. Instale e rode `byorzin-monitor setup` no computador novo (**B**).
2. Num computador que já está no grupo (**A**): painel → **Máquinas** → **Gerar código**
   (ou `byorzin-monitor pair`).
3. No **B**, digite o endereço do A e o código em **Máquinas** → *Tenho um código*, ou rode:

   ```bash
   byorzin-monitor pair 192.168.1.10 482913    # IP do A + o código de 6 dígitos mostrado no A
   ```

Pronto: nenhum token copiado à mão. Máquinas na mesma rede também aparecem em *Encontradas na
rede*; máquinas desligadas continuam na tela, apagadinhas. Por Tailscale ou WireGuard, pareie pelo
endereço da VPN. Guia completo: [docs/maquinas.md](docs/maquinas.md).

## Galeria

<p align="center">
  <img src="docs/img/screen.gif" alt="A tela em ação: subagentes aparecem, uma sessão espera você com moldura amarela, uma tarefa termina com confete e o Byorzin dorme e sonha" width="720"><br>
  <em>A tela: chegam subagentes, alguém espera você, uma tarefa longa termina e é hora da soneca.</em>
</p>

<p align="center">
  <img src="docs/img/panel.gif" alt="Usando o painel web: visão geral, gaveta de detalhes da sessão, escolha de layout, código de pareamento e tema claro" width="900"><br>
  <em>O painel web: visão geral, detalhes da sessão, layouts, pareamento e tema claro.</em>
</p>

| | |
|---|---|
| ![Layout Cards: uma coluna por sessão, subagentes embaixo](docs/img/layout-cards.png) **Cards** | ![Layout Palco: Byorzins com balões de fala](docs/img/layout-palco.png) **Palco** |
| ![Layout Foco: a sessão que precisa de você em destaque](docs/img/layout-foco.png) **Foco** | ![Layout Equipe: organograma com subagentes](docs/img/layout-equipe.png) **Equipe** |
| ![Layout Máquinas: uma faixa por computador](docs/img/layout-maquinas.png) **Máquinas** | ![Layout Dashboard: totais e tokens por hora](docs/img/layout-dashboard.png) **Dashboard** |
| ![Moldura amarela pulsando quando uma sessão espera você](docs/img/scene-alert.png) **Esperando você** | ![Confete quando uma tarefa longa termina](docs/img/scene-done.png) **Terminou** |
| ![Byorzin dormindo com Zzz](docs/img/scene-sleep.png) **Dormindo** | ![Byorzin sonhando com os tokens da semana](docs/img/scene-dream.png) **Sonhando** |

<details>
<summary>Os nove layouts</summary>

![Mosaico com os nove layouts](docs/img/mosaic.png)
</details>

<details>
<summary>Capturas do painel web</summary>

| | |
|---|---|
| ![Visão geral](docs/img/panel-overview.png) Visão geral | ![Detalhes da sessão](docs/img/panel-session.png) Detalhes da sessão |
| ![Layouts](docs/img/panel-layouts.png) Layouts | ![Comportamento](docs/img/panel-settings.png) Comportamento |
| ![Alertas](docs/img/panel-alerts.png) Alertas | ![Histórico](docs/img/panel-history.png) Histórico |
| ![Máquinas e pareamento](docs/img/panel-machines.png) Máquinas | ![Sobre](docs/img/panel-about.png) Sobre |
| ![Tema claro](docs/img/panel-light.png) Tema claro | ![Celular](docs/img/panel-mobile.png) Celular |
</details>

## Telas suportadas

Todos os backends desenham os mesmos quadros. Detalhes: [docs/telas.md](docs/telas.md).

| Tela | Backend | Status |
|---|---|---|
| Qualquer navegador: monitor, TV, tablet, celular, Raspberry Pi em quiosque (`/tela`) | `web` | **testado** |
| Turing Smart Screen 3.5" rev A (USB `1a86:5722`) | `turing-a` | **testado** |
| Terminal ou painel do tmux (meios-blocos em truecolor) | `terminal` | **testado** |
| Framebuffer do Linux (`/dev/fbN`: telas SPI do Raspberry Pi, HDMI sem desktop) | `framebuffer` | testado com dispositivo simulado |
| XuanFang 3.5" rev B | `turing-b` | experimental |
| WeAct Studio Display FS 3.5" / 0.96" | `weact` / `weact-096` | experimental |
| Outras telas USB | — | ainda não suportadas (contribuições de protocolo são bem-vindas) |

*Experimental* = escrito a partir da documentação pública do protocolo e com testes automatizados,
mas ainda sem teste em hardware real. Tem uma? Rode `byorzin-monitor display --backend <nome>` e
conte numa issue.

## Como funciona

```mermaid
flowchart LR
  subgraph W[workstation]
    CW[Claude Code] -- hooks --> KW[coletor :8787]
  end
  subgraph L[laptop]
    CL[Claude Code] -- hooks --> KL[coletor :8787]
  end
  subgraph S[server]
    CS[Claude Code] -- hooks --> KS[coletor :8787]
  end
  KW & KL & KS -- "rede local, token do grupo" --> P[painel :8788<br>desenha os quadros]
  P --> U[tela USB]
  P --> B[navegador /tela]
  P --> T[terminal / framebuffer]
```

Os hooks e a status line do Claude Code gravam pequenos eventos locais; o coletor transforma isso
em sessões, subagentes, tokens e limites; qualquer painel lê todos os coletores pareados e desenha
a tela. Mais: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Recursos

- **9 layouts** (cards, lista, foco, equipe, grade, palco, atividade, dashboard, máquinas), fixo
  ou em rodízio.
- **Esperando você**: moldura amarela na tela, notificação no navegador e, se quiser, push no
  celular via [ntfy](https://ntfy.sh).
- **Terminou**: confete quando um turno mais longo que N minutos acaba.
- **Limites semanal e de 5 horas** com projeção de ritmo, por conta do Claude.
- **Histórico**: ~90 dias de tokens por dia, modelo, máquina, ferramentas e agentes.
- **Cenas ociosas**: com sono, dormindo, sonhando com as estatísticas, painel da máquina (CPU, RAM,
  GPU, Ollama, Docker).
- **LLM local**: um Byorzin de fones de ouvido enquanto um modelo do Ollama está gerando.
- **Português e inglês** no painel e na tela.

Lista completa: [docs/recursos.md](docs/recursos.md).

## Perguntas frequentes

<details>
<summary><b>Funciona com assinatura Claude Pro / Max? E com chave de API?</b></summary>

Com os dois. Na assinatura, as barras semanal e de 5 horas vêm do que o Claude Code passa para a
status line. Com chave de API não há limite de assinatura, então essas barras ficam vazias;
sessões, subagentes, ferramentas, tokens e histórico funcionam igual.
</details>

<details>
<summary><b>Mostra uma LLM local?</b></summary>

Sim, o Ollama. O coletor consulta `http://127.0.0.1:11434/api/ps` (configurável em `ollama_url`)
e mostra uma sessão enquanto um modelo está gerando.
</details>

<details>
<summary><b>O painel é seguro na minha rede? E o token?</b></summary>

No próprio computador o painel abre direto. Outros aparelhos precisam do link do painel com chave
(aberto uma vez e trocado por um cookie `HttpOnly`), e toda alteração tem proteção contra CSRF. Os
coletores exigem o token do grupo, que o pareamento troca por você; a chave do painel é outro
segredo. O tráfego é HTTP simples: use numa rede local ou VPN de confiança e não exponha as portas
na internet.
</details>

<details>
<summary><b>Deixa o Claude Code mais lento?</b></summary>

Não. O hook acrescenta uma linha JSON por evento e sai; o coletor faz o resto em segundo plano.
</details>

<details>
<summary><b>Como desinstalo?</b></summary>

`byorzin-monitor uninstall` (com `--purge` apaga também configuração e dados), depois
`pipx uninstall byorzin-monitor`.
</details>

## Linha de comando

| Comando | O que faz |
|---|---|
| `byorzin-monitor setup` | instala ou atualiza neste computador (`--no-sudo`, `--no-claude`, `-y`) |
| `byorzin-monitor doctor` | diagnóstico de serviços, tela, hooks, portas e máquinas |
| `byorzin-monitor status` | resumo das sessões e máquinas |
| `byorzin-monitor pair [<ip> <código>]` | gera um código de pareamento ou entra no grupo de outro computador |
| `byorzin-monitor machines` | máquinas pareadas e as encontradas na rede |
| `byorzin-monitor panel-url` | link para abrir o painel em outro aparelho |
| `byorzin-monitor display --backend <nome>` | roda uma tela em primeiro plano (`web`, `terminal`, `turing-a`…) |
| `byorzin-monitor uninstall [--purge]` | remove serviços, regra udev e hooks |

## Privacidade e segurança

O que é gravado: nomes de eventos dos hooks, nomes de ferramentas, tipos de agente, horários,
nomes das pastas dos projetos, títulos das sessões, contagem de tokens, nomes de modelos e os
percentuais de limite. **Nunca** prompts, comandos, conteúdo de arquivos ou respostas. Os dados
ficam em arquivos locais e na sua rede (mais os pushes do ntfy, só se você ligar). Modelo de
ameaças e como reportar uma vulnerabilidade: [SECURITY.md](SECURITY.md).

## Documentação

[Arquitetura](docs/ARCHITECTURE.md) · [Máquinas e pareamento](docs/maquinas.md) ·
[Telas](docs/telas.md) · [Recursos](docs/recursos.md) · [Changelog](CHANGELOG.md)

## Próximos passos

- **Outros agentes de IA no mesmo painel** — o próximo é o **OpenAI Codex CLI** (sessões, ferramentas,
  contexto e os limites de 5h/semana dele), depois outros agentes com dados locais de sessão (ex.:
  Gemini CLI, Aider). Cada provedor ganha a sua cor de Byorzin.
- Layouts nativos para telas grandes (monitores e TVs 16:9) e telas em pé.
- Mais telas USB testadas em hardware real — ajuda é bem-vinda (veja `docs/telas.md`).

## Contribuindo

Relatos de bugs, telas testadas em hardware real e layouts novos são bem-vindos. Veja
[CONTRIBUTING.md](CONTRIBUTING.md).

## Licença

- Código: [MIT](LICENSE).
- O mascote **Byorzin** (personagem, nome e arte) é © BYOR-SEC e licenciado para uso apenas
  dentro deste projeto; veja [LICENSE-ASSETS.md](LICENSE-ASSETS.md).
- Projeto independente, sem afiliação nem endosso da Anthropic. "Claude" e "Claude Code" são
  marcas da Anthropic.

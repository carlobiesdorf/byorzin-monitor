# Recursos do dia a dia

Este documento explica os alertas, o histórico, o LLM local e o detalhe da sessão, e as configurações
de cada um. Todos os ajustes ficam na aba **Ajustes** do painel, nos grupos "Alertas e notificações"
e "LLM local". Ficam gravados em `display.json` e são copiados para as outras máquinas, como os demais.

## Onde cada coisa roda

| Peça | Quem faz |
|---|---|
| Detectar "esperando você" e "terminou" | coletor (`alerts.py`), a partir dos eventos dos hooks |
| Enviar para o ntfy | coletor da **máquina dona da sessão** |
| Efeito na tela | display (`display/effects.py`), lendo `alerts` do `/state` de todas as máquinas |
| Notificação do navegador e som | página do painel, lendo `alerts` de `/api/state` |
| Histórico | cada coletor guarda o seu (`history.py`); o painel soma todas as máquinas |
| Sessão do LLM local | coletor (`ollama.py`) |

**Por que o ntfy sai do coletor:** só o coletor da máquina onde a sessão roda recebe os eventos
dela, então cada aviso nasce num lugar só. Mesmo com três máquinas e dois painéis abertos, o celular
recebe uma notificação por transição. Se fosse disparado pelo display ou pelo painel, cada máquina com
tela ou painel mandaria uma cópia.

## 1. "Esperando você"

Uma sessão passa a esperar você quando chega um `PermissionRequest`, ou uma `Notification` do tipo
`permission_prompt`, `elicitation_dialog` ou `idle_prompt`. Esse último é o aviso que o Claude Code
manda quando a sessão fica parada esperando a próxima mensagem.

Para não virar spam:
- só a **transição** para "esperando" avisa. O `PermissionRequest` e a `Notification` do mesmo pedido
  contam como um aviso só. A sessão precisa voltar a trabalhar para avisar de novo;
- há um **intervalo mínimo por sessão** (`alert_cooldown_seconds`, padrão 90 s);
- um "ociosa esperando" logo depois de um "terminou" da mesma sessão não avisa de novo;
- eventos antigos relidos do `events.jsonl` quando o coletor reinicia não avisam. Só avisam eventos
  com menos de 60 s.

| Ajuste | Padrão | O que faz |
|---|---|---|
| `alert_screen` | ligado | moldura amarela pulsando na tela, por cima do layout atual |
| `alert_screen_seconds` | 8 s | duração do efeito |
| `alert_max_brightness` | ligado | brilho 100% enquanto o efeito dura (também à noite) |
| `alert_idle` | ligado | avisa também o `idle_prompt` (sessão ociosa esperando) |
| `alert_cooldown_seconds` | 90 s | intervalo mínimo entre avisos do mesmo tipo na mesma sessão |
| `alert_browser` | ligado | notificação do navegador (precisa permitir em cada navegador) |
| `alert_sound` | ligado | bipe curto no painel, gerado com WebAudio, sem arquivo de som |

No navegador é preciso clicar em **Permitir notificações aqui** (seção Alertas do painel). Esse clique
também libera o áudio, porque os navegadores só tocam som depois de uma interação na página. O painel
precisa estar aberto numa aba, que pode ficar em segundo plano. Ao abrir o painel, os alertas que já
existiam não são repetidos.

## 2. "Terminou"

Quando uma sessão começa a trabalhar (mensagem sua, ferramenta, agente), o coletor anota o início do
turno. No `Stop`, se o turno durou mais que `done_minutes`, nasce um alerta "terminou". O tempo esperando
permissão no meio do turno conta como parte do turno.

| Ajuste | Padrão | O que faz |
|---|---|---|
| `done_minutes` | 5 min | duração mínima do turno para comemorar e avisar |
| `done_celebrate` | ligado | cena de ~6 s na tela: Byorzin pulando, confete e nome da sessão |

O "terminou" também vai para o navegador e para o ntfy (ver abaixo).

## 3. ntfy (celular)

Desligado por padrão. Para ligar: escolha um tópico difícil de adivinhar, assine-o no app do ntfy e
preencha os campos.

| Ajuste | Padrão | O que faz |
|---|---|---|
| `ntfy_enabled` | desligado | liga o envio |
| `ntfy_server` | `https://ntfy.sh` | servidor (pode ser o seu) |
| `ntfy_topic` | vazio | tópico; vazio = não envia |
| `ntfy_waiting` | ligado | envia "Esperando você" |
| `ntfy_done` | ligado | envia "Terminou" |

O envio é um `POST` JSON na raiz do servidor (`{"topic", "title", "message", "tags", "priority"}`),
formato que aceita acentos. **Privacidade:** a mensagem leva só o nome do projeto (a pasta), a máquina
e o motivo, nunca o título da sessão, porque o título pode revelar o assunto. O coletor lê os ajustes
do `display.json` da própria máquina. Numa máquina sem painel, os ajustes só chegam se forem copiados
para lá.

## 4. Histórico

Cada coletor guarda agregados por dia em `~/.local/state/byorzin-monitor/history.json`, por 90 dias:

- **tokens**: o total de cada dia vem do contador de tokens (`tokens.json`), que soma toda resposta
  lida dos transcripts uma vez só; hoje e o primeiro dia de uma instalação nova acompanham o `/state`
  a cada ciclo, sem contar em dobro;
- **tokens por modelo**: somados dos baldes por hora (janela de 8 dias). Um dia que começou antes da
  janela tem baldes já descartados, então ali o valor só aumenta, nunca diminui;
- **sessões**: sessões diferentes com algum evento no dia;
- **ferramentas**: contagem de `PreToolUse` por nome. As ferramentas MCP são agrupadas por servidor
  (`mcp:github`);
- **agentes**: `SubagentStart` por tipo;
- **mensagens suas**: `UserPromptSubmit`;
- **tempo trabalhando**: soma dos intervalos entre eventos enquanto a sessão está trabalhando. O
  intervalo é dividido na meia-noite. Para de contar ao esperar você ou no `Stop`. Intervalos maiores
  que 15 min são ignorados. Sessões simultâneas somam.

Quando o coletor reinicia, ele relê o `events.jsonl`. Para não contar duas vezes, guarda o horário do
último evento já contado. A rota é `GET /history?days=N` (1 a 90) no coletor e exige o token, como o
`/state`. O painel junta todas as máquinas em `GET /api/history?days=N`, e a aba **Histórico** mostra:
números do período, tokens por dia (barras empilhadas por máquina, com detalhe ao passar o mouse),
tokens por máquina e por modelo, ferramentas mais usadas e agentes iniciados. O período pode ser 7, 30
ou 90 dias.

### Ordem dos eventos

Cada hook roda como um processo separado e assíncrono, então as linhas do `events.jsonl` podem chegar
fora de ordem. O coletor ignora mudanças de status mais antigas que a última aplicada na sessão,
guarda os subagentes já encerrados (`SubagentStop`) para que um evento atrasado não os traga de
volta, e ignora eventos atrasados de uma sessão já encerrada. Subagentes sem `SubagentStop` continuam
sumindo após 30 min sem eventos. Um pedido de permissão (ou aviso de espera) **de dentro de um
subagente** deixa a sessão "esperando você" (e o subagente marcado como esperando); quando o agente
volta a trabalhar ou termina, a sessão volta ao estado anterior. A ferramenta do agente nunca vira a
ferramenta da sessão.

### Privacidade do hook

O hook grava só metadados: sessão, evento, nome da ferramenta, id e tipo do agente, nome da pasta do
projeto e horário. `notification_type`, `source` e `reason` só entram se forem valores conhecidos
(senão viram `other`). O texto de erro de ferramentas (`PostToolUseFailure`) nunca é gravado; no
`StopFailure` grava só o tipo (`rate_limit`, `overloaded`, `authentication_failed`, `billing_error`...,
ou `other`).

## 5. LLM local (Ollama)

O coletor consulta `GET /api/ps` do Ollama a cada 3 s. O endereço vem de `ollama_url` no
`config.toml`, com padrão `http://127.0.0.1:11434` (vale também para os modelos carregados nas
métricas da máquina). O Ollama não informa se está gerando, então vale
esta heurística:

1. existe modelo carregado; **e**
2. o `expires_at` dele mudou desde a última leitura (o Ollama renova o keep-alive a cada requisição),
   **ou** a GPU (nvidia-smi) está acima de `llm_gpu_pct`; **ou** o modelo acabou de ser carregado.

Cada sinal mantém o estado "gerando" por 15 s. Depois disso, a sessão fica como ociosa por
`llm_linger_seconds` e some. Um modelo que já estava carregado quando o coletor subiu não conta como
uso. Sem Ollama, a conexão é recusada: o coletor tenta de novo a cada 30 s e nada aparece.

A sessão especial tem `kind = "llm"`, `id = "llm:<modelo>"` e nome = modelo. Na tela, ela aparece com
um **Byorzin rosa de fone de ouvido** e o status "gerando". Ela não dispara o susto de sessão nova. No
painel, recebe a etiqueta "LLM local".

| Ajuste | Padrão | O que faz |
|---|---|---|
| `llm_session` | ligado | mostra o Ollama como sessão |
| `llm_gpu_pct` | 30% | GPU acima disso com modelo carregado = gerando |
| `llm_linger_seconds` | 60 s | quanto tempo continua na tela depois de parar |

## 6. Detalhe da sessão

Na aba **Tela**, clique numa sessão. Abre uma janela com projeto, título, máquina, modelo, status,
contexto %, tokens (8 dias), custo estimado (o da status line), tempo aberta, última atividade,
subagentes rodando e os últimos 20 eventos. Os eventos guardam só o tipo, a ferramenta e o tipo de
agente. O painel busca em `GET /session?id=...` no coletor da máquina dona (com token), por
`GET /api/session?host=...&id=...`.

## Testar

- Cenas novas: aba **Cenas** → "Esperando você (moldura)" e "Terminou (comemoração)", com prévia e
  botão **Testar na tela**.
- Testes automáticos: `python -m unittest discover -s tests`. Os testes usam pastas temporárias e as
  portas 58797/58798.
- Simulação manual: com um coletor de teste rodando, mande eventos pelo hook, por exemplo
  `echo '{"session_id":"x","hook_event_name":"PermissionRequest","cwd":"/tmp/p"}' | byorzin-monitor hook`.

# Várias máquinas

O Byorzin mostra numa tela só as sessões do Claude Code de todos os seus computadores. Cada
computador roda um **coletor** (porta 8787) e um **painel** (porta 8788); a tela, o painel e o
`byorzin-monitor status` de qualquer máquina leem o coletor local e o de cada máquina pareada.

## Como juntar duas máquinas

1. Instale nas duas: `byorzin-monitor setup`.
2. Na máquina **A**, gere um código: painel → aba **Máquinas** → **Gerar código**
   (ou `byorzin-monitor pair` sem argumentos). Ele tem 6 dígitos, vale 5 minutos e é de uso único.
3. Na máquina **B**, use o código:
   - pelo painel de B: aba **Máquinas** → em *Encontradas na rede*, clique **Parear** na máquina A
     e digite o código (ou digite o endereço do painel de A em *Tenho um código*);
   - ou pela linha de comando: `byorzin-monitor pair 192.168.1.10 482913`
     (aceita `ip`, `ip:porta-do-painel` ou URL).

Pronto: B passa a usar o token de A, A e B viram peers uma da outra e as máquinas que já estavam
pareadas com A também recebem B. Coletor, painel e tela releem o `config.toml` sozinhos em
poucos segundos; não precisa reiniciar nada.

Para conferir: `byorzin-monitor machines` (pareadas e encontradas) e `byorzin-monitor doctor`.

### Remover uma máquina

Painel → **Máquinas** → **Remover** no cartão dela. A máquina sai dos peers desta e, se estiver
online, esta também sai dos peers dela. As outras máquinas do grupo não são avisadas.

## Descoberta na rede local

Cada coletor anuncia-se por **UDP broadcast** na porta **8789** a cada 10 s e responde na hora
a quem pergunta "quem está aí?" (o painel pergunta ao subir). O anúncio leva só: nome da
máquina, versão, portas do coletor e do painel e um id aleatório da instalação
(`~/.config/byorzin-monitor/install_id`). **Nunca o token.**

O painel lista em *Encontradas na rede* quem anuncia e ainda não está pareado.

Broadcast não atravessa roteadores nem VPN: em redes diferentes, use o endereço direto
(`byorzin-monitor pair <ip> <código>`) — veja *Fora de casa* abaixo.

## Máquinas fora do ar

Uma máquina que para de responder continua na tela por 30 s como se nada tivesse acontecido
(reinício do coletor, wifi piscando). Depois disso ela fica **offline**:

- na barra de cima da tela aparece apagada, com "visto há" (ex.: `notebook 2h`);
- no painel, o cartão dela mostra "offline · visto há …" e a data do último contato;
- as sessões dela **saem** das listas de sessões ativas (não dá para saber se ainda existem);
  no layout **Máquinas** elas aparecem como Byorzins dormindo e apagados, do jeito que estavam
  no último contato.

O último estado de cada máquina é guardado em `~/.local/state/byorzin-monitor/seen.json`, então
continua visível depois de reiniciar o painel ou a tela.

## Várias contas

Cada computador pode estar logado numa conta diferente do Claude (ex.: o notebook na conta
pessoal e o servidor na do trabalho). Cada conta tem os seus limites de uso (semana e janela de
5 h), então o monitor separa os limites por conta:

- **uma conta só** (o normal): nada muda — a mesma tela, o mesmo painel;
- **duas ou mais**: a barra de cima mostra as 5 h de cada conta com um marcador curto (`P`, `T`;
  `Pe`/`Pr` se as iniciais coincidirem), os rodapés mostram a semana de cada conta com o rótulo,
  e as telas que já dizem a máquina da sessão (Foco, Grade, Palco) mostram também a conta
  (`server · Trabalho`); no layout **Máquinas** o marcador aparece ao lado do nome da máquina.
  Cabem até 3 contas; com mais, aparecem as 2 mais altas e `+N`;
- o **alerta de limite** dispara quando *qualquer* conta passa do limiar e diz qual
  (`conta Pessoal`); o Byorzin engorda com a maior porcentagem;
- no painel, os cartões de semana e 5 h mostram o maior valor e uma linha por conta; a tabela de
  sessões, a gaveta da sessão e o cartão de cada máquina mostram a conta; em **Máquinas → Contas**
  dá para trocar o rótulo de cada conta (replicado para as outras máquinas, como os demais ajustes).

De onde vem a conta: o coletor e a status line leem `oauthAccount` em
`$CLAUDE_CONFIG_DIR/.claude.json` (se existir) ou `~/.claude.json`, com cache pela data de
modificação do arquivo (um `/login` em outra conta é percebido na próxima leitura).

Privacidade: pela rede saem só um **id derivado** (12 primeiros hex do sha256 de
`accountUuid:organizationUuid`; a mesma pessoa numa organização de equipe é outra conta, com
outros limites) e um **rótulo**. O rótulo padrão é o nome da organização, se for de equipe, senão
o primeiro nome, senão `conta-<4 hex>`; nunca o e-mail, o nome completo nem o uuid.

Detalhes:

- `rate.json` guarda um snapshot por conta (`{"v": 2, "accounts": {id: {...}}}`); o formato antigo
  é lido como sendo da conta atual. "Na mesma janela o uso só sobe" continua valendo, por conta.
- `/state` ganhou `account` (`{"id", "label"}` desta máquina), `rates` (`{id: snapshot}`, inclui
  outra conta que usou esta máquina nas últimas 24 h) e `account` em cada sessão; o campo antigo
  `rate` continua lá (= a conta desta máquina), para máquinas com versão antiga.
- Máquina com versão antiga (só `rate`, sem conta) entra na única conta conhecida; se houver
  várias, na que tem a mesma janela (`resets_at`); sem nenhuma conta conhecida, tudo funciona
  como antes.
- Chave de API (sem `oauthAccount`) vira a conta `API key`: aparece no painel, mas sem barra de
  limites (a status line não recebe `rate_limits`).
- Para ver como fica sem ter duas contas: no painel, **Layouts → Demo: 2 contas**.

## Segurança

- O **token** protege o `/state` dos coletores e a replicação de ajustes entre painéis. Ele só
  sai de uma máquina pela troca de um código válido; não aparece no painel nem nos anúncios.
- **Código**: 6 dígitos, 5 minutos, uso único. Cada código aceita 5 erros e é invalidado.
  Além disso, cada IP pode errar no máximo 10 vezes em 5 minutos, e todos juntos 30 vezes —
  depois disso o painel responde "muitas tentativas" (HTTP 429) até a janela passar.
- **Gerar código, parear e remover** exigem um painel autenticado: aberto neste próprio computador
  ou num aparelho que entrou pelo link com a chave do painel (abaixo). Todo POST do painel também
  passa pela proteção contra CSRF (JSON + cabeçalho `X-Byorzin: 1` + `Origin` igual ao endereço do
  painel), então outro site aberto no seu navegador não consegue disparar essas ações.
- **Remover** só aceita máquinas que estão na lista de pareadas: o token do grupo nunca é enviado
  para um endereço que veio do pedido.
- Tudo trafega em **HTTP sem criptografia** na rede local, inclusive o token no momento do
  pareamento. Use em rede de confiança (casa, escritório), não em wifi público.
- **Acesso ao painel (porta 8788)**: neste computador (`http://localhost:8788`) abre direto. De
  outro aparelho da rede (celular, tablet, outro PC), **abra o link mostrado no painel desta
  máquina** (**Máquinas** → *Acesso de outro aparelho*), ou por `byorzin-monitor panel-url` /
  `curl http://127.0.0.1:8788/api/panel-url`. O link (`http://IP:8788/?key=...`, ou `/tela?key=...`
  para quiosque) é aberto uma vez: o painel troca a chave por um cookie `HttpOnly` e tira a chave
  da URL. Sem o cookie, a página explica como obter o link. A chave fica em
  `~/.config/byorzin-monitor/panel_key` (600), é diferente do token do grupo, e **Gerar nova chave**
  (ou apagar o arquivo) invalida links e cookies antigos.
- `panel_auth = "off"` no `config.toml` volta ao painel aberto para a rede (**inseguro**: qualquer
  um na rede vê as sessões e muda os ajustes; só o tópico ntfy continua escondido).
- Remover uma máquina não troca o token: se ela foi comprometida, gere um token novo
  (`token = "..."` no `config.toml` de uma máquina) e pareie as outras de novo.

### Firewall

Libere, só para a rede local:

| Porta | Protocolo | Para quê |
|---|---|---|
| 8787 | TCP | coletor (`/state`) |
| 8788 | TCP | painel (inclui o pareamento) |
| 8789 | UDP | descoberta (anúncios) |

O `byorzin-monitor setup` faz isso sozinho se o `ufw` estiver ativo (rede padrão
`192.168.0.0/16`, mude com `--lan`).

## Configuração (`~/.config/byorzin-monitor/config.toml`)

| Chave | Padrão | |
|---|---|---|
| `token` | gerado no setup | segredo comum do grupo (preenchido pelo pareamento) |
| `peers` | `[]` | coletores das outras máquinas (preenchido pelo pareamento) |
| `hostname` | nome do computador | nome mostrado na tela (relido sem reiniciar; duas máquinas com o mesmo nome aparecem como `nome` e `nome (2)`) |
| `port` / `panel_port` | 8787 / 8788 | portas do coletor e do painel |
| `discovery` | `true` | anunciar e procurar máquinas na rede |
| `discovery_port` | 8789 | porta UDP da descoberta |
| `discovery_address` | `255.255.255.255` | destino dos anúncios (ex.: `192.168.1.255`) |
| `panel_auth` | `"lan"` | `"lan"`: outro aparelho precisa do link com a chave; `"off"`: painel aberto (inseguro) |
| `panel_bind` | `"0.0.0.0"` | endereço onde o painel escuta (`"127.0.0.1"` = só este computador) |
| `pair_from_anywhere` | `false` | só com `panel_auth = "off"`: aceitar gerar código/parear de qualquer IP |

Os metadados das máquinas pareadas (id, nome, endereço do painel) ficam em
`~/.config/byorzin-monitor/machines.json`. A alternativa manual continua valendo:
`byorzin-monitor setup --token <token> --peer http://<ip>:8787`.

## Fora de casa (Tailscale / WireGuard)

O coletor não muda nada: basta as máquinas se alcançarem por IP.

- **Tailscale**: instale nas máquinas, e pareie usando o IP `100.x.y.z` (ou o nome MagicDNS):
  `byorzin-monitor pair 100.101.102.103 123456`. A descoberta por broadcast não funciona pela
  VPN, mas o pareamento direto sim. Restrinja as portas 8787/8788 à interface `tailscale0`
  ou às ACLs do Tailscale.
- **WireGuard**: igual, usando o IP do túnel (ex.: `10.0.0.2`). Libere 8787/8788 TCP na
  interface `wg0`.

Um detalhe: quem gera o código vê o pedido chegar do IP da VPN e grava esse endereço como
peer; então pareie sempre pelo endereço que a outra máquina vai usar para te alcançar.

## Testar sem duas máquinas

Dá para simular duas máquinas na mesma, cada uma com sua pasta e suas portas:

```sh
for m in a b; do
  mkdir -p /tmp/bz-$m/cfg/byorzin-monitor /tmp/bz-$m/st
done
cat > /tmp/bz-a/cfg/byorzin-monitor/config.toml <<EOF
token = "a"
hostname = "maq-a"
port = 38787
panel_port = 38788
discovery_port = 38789
discovery_address = "127.255.255.255"
EOF
# idem para b com maq-b, 48787, 48788 (mesma discovery_port)
XDG_CONFIG_HOME=/tmp/bz-a/cfg XDG_STATE_HOME=/tmp/bz-a/st byorzin-monitor collector &
XDG_CONFIG_HOME=/tmp/bz-a/cfg XDG_STATE_HOME=/tmp/bz-a/st byorzin-monitor panel &
# ... o mesmo para b; depois:
XDG_CONFIG_HOME=/tmp/bz-a/cfg XDG_STATE_HOME=/tmp/bz-a/st byorzin-monitor pair
XDG_CONFIG_HOME=/tmp/bz-b/cfg XDG_STATE_HOME=/tmp/bz-b/st byorzin-monitor pair 127.0.0.1:38788 <código>
```

Para simular duas contas, dê a cada "máquina" o seu `CLAUDE_CONFIG_DIR` com um `.claude.json`
falso (`{"oauthAccount": {"accountUuid": "...", "displayName": "Ana"}}`) e mande um JSON com
`rate_limits` para `byorzin-monitor statusline` com o mesmo ambiente.

Testes automáticos: `python -m unittest discover -s tests`.

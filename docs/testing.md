# Como verificar que está funcionando

Três níveis de verificação, do mais rápido ao mais completo: a suíte de testes,
o servidor local com `curl`, e o boot de verdade numa máquina virtual.

Todos os comandos partem da raiz do repositório (`nutellaboot3/`).

## 1. A suíte de testes

```bash
.venv/bin/python -m pytest
```

São 481 testes em cerca de 36 s. O que cada arquivo cobre:

| Arquivo | O que garante |
|---|---|
| `test_fsdb.py` | escrita atômica e travas do banco-filesystem; dois escritores concorrentes não perdem dados |
| `test_auth.py` | as classes de credencial (admin, imagem, serviço, máquina) e seus limites |
| `test_health.py` | o endpoint de saúde |
| `test_boot_endpoints.py` | manifest com todos os seeders vivos e o CDN por último, TTL de seeder, geração do stuff, chave de boot, criação e criação em massa de imagens |
| `test_bootstrap_shell.py` | a lógica shell do initrd: precedência de configuração, geração do `wpa_supplicant.conf`, pin de `/etc/hosts`. Inclui três testes de regressão que **falham se alguém**: usar `read` interativo no caminho de boot, desligar a verificação de certificado, ou redefinir as funções de rede dentro do stuff |
| `test_config.py` | validação do formulário, campos bloqueados, senha guardada só como hash, upload de wallpaper |
| `test_commands.py` | ciclo de vida do comando (enfileirar, buscar, confirmar), lista de comandos permitidos, bloqueio de tela, teto de tamanho dos logs |
| `test_longpoll_async.py` | a latência real do long-poll no mesmo event loop: bloqueio chega em menos de 1,5 s, e 50 máquinas simultâneas em menos de 3 s |
| `test_roster_sse.py` | roster, vínculo time↔máquina, dados da tela de bloqueio, e que esses dados não vazam segredo |
| `test_moj_webhooks.py` | chaves de serviço com escopo, filtro por imagem, e entrega de webhook assinado a um receptor real |
| `test_layer_builder.py` | construção de camada **sem root**, ponta a ponta, com poda verificada — inclusive que nenhum hash de senha sai na camada |
| `test_i18n_locales.py` | os três idiomas têm exatamente as mesmas chaves, sem valores vazios, e toda chave usada nas páginas existe |
| `test_live_server.py` | sobe um `uvicorn` de verdade e testa SSE e latência de bloqueio por HTTP |
| `test_models.py` | modelos criáveis: criar, duplicar herdando camadas e cadeados, montar/reordenar/remover camada, e que a ordem chega no manifest; apagar recusa (409) enquanto houver site-image derivada |
| `test_subadmin.py` | o isolamento: o código de convite como credencial de console, nome reservado recusado, o que é de outro dono responde **404**, cotas contadas por varredura, suspensão e revogação, e que o token da imagem **não** vira console |
| `test_legacy_paths.py` | `/api/v1/images/…` continua respondendo — lê o `agent.sh` embarcado nas camadas publicadas e confere caminho por caminho |
| `test_migrate_names.py` | a migração de nomes: `--dry-run` não mexe em nada, é idempotente e não sobrescreve destino existente |
| `test_web_js.py` | um *no-undef* mínimo para o JavaScript das telas (não há node nesta máquina): acusa uso de variável sem declaração que não seja global do navegador — a classe do "template is not defined" que só explodia no clique. Pende para o falso negativo de propósito; não substitui um linter de verdade |
| `test_web_ids.py` | todo id que o JavaScript procura existe no HTML da tela (erro que deixaria a tela em branco, sem mensagem) |
| `test_tool_routes.py` | toda rota `/api/v1/…` citada em `tools/` existe na API de verdade |
| `test_boot_ui.py` | o kit de tela do boot: cada glifo da fonte tem 5 linhas, o banner quebra quando não cabe, o passo fecha a linha antes de um aviso, nenhum temporário é compartilhado entre funções (foi o que causou `sleep RAM`) e **nenhuma mensagem de tela tem acento** — o proxy de "sobrou português" |
| `test_boot_screens.py` | as telas fatais: o diagnóstico de disco escolhe entre Fast Startup, pouco espaço, disco não detectado e sistema de arquivos não suportado; cada tela **cabe em 25 linhas** (senão o banner rola para fora, como aconteceu na primeira verificação em VM) e toda tela diz o que fazer |
| `test_camada_telemetria.py` | a camada de telemetria nasce com todos os coletores, dono `root:root`, bit de execução onde faz falta e sem segredo; o nome muda quando o conteúdo muda |
| `test_logs.py` | ingestão de log com teto por requisição (413) e por máquina (mantém a cauda), leitura da cauda, autenticação, e que a telemetria também passou a ter teto |
| `test_session.py` | a sessão do console: o cookie sozinho entra (é o que o reload passa a fazer), as flags do cookie, expiração, e a revogação de verdade — trocar a chave de administração, revogar o convite ou suspender o sub-admin derruba a sessão na hora; mais o par de CSRF (cookie sem o cabeçalho `X-NB-Console` é recusado, com ele é aceito) e a garantia de que **Bearer continua funcionando** para as ferramentas e o MOJ |
| `test_layer_roles.py` | o papel de cada camada: `role` inválido é recusado, `replace_role` troca a base **mantendo a posição** (por último), e registrar uma base com nome diferente deixa **uma** base e não duas — a regressão que fazia a máquina baixar duas raízes; mais a migração de papéis (dedução, idempotência, respeito ao que já foi marcado à mão) |
| `test_nova_temporada.py` | o comando de temporada contra um uvicorn de verdade: herda camadas e cadeados, não toca no modelo anterior, preenche um modelo que ficou vazio, não empilha bases ao rodar duas vezes, e **falha alto** com nome de modelo errado ou chave errada (era o que terminava com sucesso sem registrar nada) |
| `test_alerts.py` | o alerta de dispositivo **não some sozinho**, sobrevive a recarga, só dispensa com credencial de console, a máquina não dispensa o próprio alerta, e a regra de udev ignora o pendrive de boot |
| `test_boot_key.py` | a chave de boot fecha os endpoints de boot e a rotação invalida a antiga |
| `test_credentials.py` | as credenciais de uma imagem já criada podem ser relidas sem rotacionar (o que quebraria links já distribuídos) |
| `test_schema_locks.py` | o cadeado por campo do modelo e o wallpaper travado por imagem |
| `test_self_service.py` | criação por convite: cota, código inválido, nome reservado e modelo não-público |
| `test_requests.py` | a fila de pedidos de quem não tem código: enviar, aprovar emitindo código, recusar |
| `test_ratelimit.py` | o limite de taxa das rotas públicas, incluindo o respeito ao `X-Forwarded-For` |
| `test_publish.py` | publicação de arquivos no servidor de arquivos externo, com repetição em caso de falha |

Sobre o `test_live_server.py`: ele existe porque o transporte ASGI do `httpx`
**não** faz streaming — executa a aplicação até o fim antes de devolver a
resposta, o que deixaria um fluxo SSE (que não termina) pendurado para sempre.
A única forma honesta de testar SSE é contra um servidor real.

O `test_layer_builder.py` é pulado automaticamente se as ferramentas rootless
não estiverem instaladas (veja `docs/layer-builds.md`).

## 2. O ambiente local

```bash
tools/nb3-init              # chave de administração (só na primeira vez)
tools/nb3-seed-testdata     # modelo de exemplo e a imagem testes3
tools/nb3-dev               # sobe o servidor em 127.0.0.1:8890
```

Cada um imprime as credenciais que gera **uma vez**: o `nb3-init`, a chave de
administração; o `nb3-seed-testdata`, o token, a chave de máquina e a chave de
boot da imagem `testes3`. Anote. Os dois são idempotentes — rodar de novo não
sobrescreve o que já existe, e o `nb3-init` não emite outra chave sem
`--nova-chave`.

São dois comandos porque eram um só: ele gravava o hash da chave de
administração e estourava no passo seguinte, antes de imprimi-la. A chave em
claro se perdia e o arquivo já existia, então repetir não adiantava — quem
instalava numa máquina limpa ficava trancado do lado de fora.

O `nb3-dev` sobe um único worker. Isso não é detalhe de configuração: o
long-poll e o SSE mantêm os sinais de acordar em memória, então **mais de um
worker quebraria a entrega de comandos**.

Já existe um proxy nginx apontando para esse servidor:

```
https://nutellaboot.charge.naquadah.com.br:8443  →  localhost:8890
```

Use o endereço público quando quiser testar com TLS de verdade (é o que as
máquinas usam) e o `localhost` para depurar sem passar pelo proxy.

### Verificação por curl

```bash
B=https://nutellaboot.charge.naquadah.com.br:8443
BK=nb3b_...          # chave de boot de testes3
TK=nb3i_...          # token da imagem
AK=nb3a_...          # chave de administração

# saúde do serviço
curl -s "$B/api/v1/health"

# o que o initrd checa antes de tudo
curl -s "$B/boot/v3/sanity"          # deve responder: penguin
curl -s "$B/boot/v3/time"            # hora do servidor, em segundos

# lista de camadas (precisa da chave de boot)
curl -s "$B/boot/v3/testes3/manifest" -H "X-NB-Boot-Key: $BK"

# o script de boot, montado na hora
curl -s "$B/boot/v3/testes3/stuff" -H "X-NB-Boot-Key: $BK" | head -20

# sem a chave, o servidor recusa
curl -s -o /dev/null -w '%{http_code}\n' "$B/boot/v3/testes3/manifest"   # 401

# configuração da imagem (token da imagem)
curl -s "$B/api/v1/site-images/testes3/config" -H "Authorization: Bearer $TK"

# listagem de imagens (chave de administração)
curl -s "$B/api/v1/site-images" -H "Authorization: Bearer $AK"
```

Vale conferir que o `stuff` gerado é shell válido antes de mandar para uma
máquina:

```bash
curl -s "$B/boot/v3/testes3/stuff" -H "X-NB-Boot-Key: $BK" > /tmp/stuff.sh
sh -n /tmp/stuff.sh && echo "sintaxe ok"
```

A documentação das rotas fica em `$B/api/v1/docs` (OpenAPI, gerado
automaticamente).

## 3. Boot em máquina virtual

```bash
tools/nb3-run-test
```

Ele gera o pendrive de teste (sem root), cria um "disco da máquina" de 40 GB
esparso se ainda não existir, e sobe o qemu em UEFI com os dois discos. Opções
úteis:

| Opção | Efeito |
|---|---|
| `--image 26spsp` | outra imagem |
| `--server URL` | outro servidor |
| `--fresh-disk` | descarta o disco e começa do zero |
| `--build-only` | só gera o pendrive, não sobe a VM |
| `--headless` | sem janela gráfica |

### O detalhe do `10.0.2.2`

Dentro do qemu com rede de usuário (SLIRP), a máquina hospedeira é sempre
`10.0.2.2`. Além disso, o nome do servidor de teste resolve **apenas em IPv6**,
e o SLIRP é IPv4 — a máquina virtual não conseguiria chegar nele por DNS.

Por isso o `nb3-run-test` grava no `nutellaboot.conf` do pendrive de teste:

```
NB_HOSTS=nutellaboot.charge.naquadah.com.br 10.0.2.2
```

Isso escreve a linha no `/etc/hosts` do initrd. O nome continua o mesmo — muda
só o endereço — então **o certificado continua sendo validado normalmente**.
Não há exceção de TLS no ambiente de teste.

O `aria2c` roda com `--async-dns=false` justamente para honrar esse
`/etc/hosts`; com o resolvedor assíncrono ele ignoraria o arquivo.

### Screenshot sem olhar a tela

```bash
tools/nb3-qemu-shot data/test-usb.img /tmp/tela.png --wait 8
```

Sobe a imagem no qemu, espera os segundos indicados, tira um screenshot e
encerra. É como se verifica que o pendrive dá boot sem precisar de hardware nem
de alguém olhando. Com `--disk` você anexa o disco da máquina, e com `--keep` a
VM continua rodando depois do screenshot.

Momentos úteis para capturar:

| Espera | O que deve aparecer |
|---|---|
| ~6 s | o menu do GRUB com as quatro entradas |
| ~45 s | "Booting…" e as primeiras mensagens do kernel |
| ~3 min | o initrd baixando as camadas (depende da rede) |

### O que verificar num boot completo

1. o menu do GRUB aparece e a entrada padrão inicia;
2. a mensagem "PODE RETIRAR O PENDRIVE AGORA" aparece cedo;
3. a rede sobe e o `sanity` responde (sem erro de certificado);
4. as camadas são baixadas e o md5 confere;
5. o sistema chega à tela de login;
6. a máquina aparece no painel `/hotconfig/`;
7. bloquear pelo painel acende o cadeado no cartão e a tela muda na VM em
   poucos segundos;
8. matar o processo da tela na VM: ela volta em até 3 segundos;
9. a senha de emergência destrava.

## 4. A tela de bloqueio

Os três temas podem ser vistos no navegador, sem máquina nenhuma:

```
http://127.0.0.1:8890/lock/
```

A página mostra `clássico`, `animado` e `minimalista` lado a lado, com dados de
exemplo, e cada um pode ser aberto em tela cheia. É o que a pessoa escolhe no
campo "Tema da tela de bloqueio" do configureitor.

Para testar com dados reais de um time, abra um tema direto passando o mesmo
formato que o `maratona-wait` usa:

```
/lock/themes/animado/index.html?lang=pt&info=<JSON codificado com encodeURIComponent>
```

Mexa o mouse ou digite: o aviso "NÃO mexa no mouse nem no teclado" aparece nos
três idiomas e escala visualmente se o toque continuar.

Os temas usam script clássico (`<script src=…>`), não módulos ES. Isso não é
estilo: os temas são carregados de `file://` dentro do WebKit, e imports de
módulo são bloqueados por CORS nesse esquema — a tela abriria em branco na
máquina do competidor.

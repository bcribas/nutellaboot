# Pull requests: como revisar, decidir e aplicar

Este é o padrão para **todo PR no NutellaBoot 3**, de quem é de fora ou de
dentro. Vale para quem mantém e para os agentes (Claude Code). Foi adaptado do
padrão do MOJ, que nasceu de uma rodada em que a revisão adversária achou
defeitos reais em PRs que pareciam certos.

Aqui o custo de errar é maior que numa tela: o código de `client/` vai dentro do
initrd e das camadas publicadas, roda como root nas máquinas de prova, e uma
máquina já instalada não se atualiza sozinha (invariante 10 do `CLAUDE.md`).

Quem **envia** um PR: veja [Para quem contribui](#para-quem-contribui) no fim.

## Princípios

1. **Quem decide é o mantenedor, PR a PR.** Nada é aplicado, mesclado, fechado
   ou comentado por conta própria.
   - Para cada PR vai uma recomendação e o racional: aplicar como está, aplicar
     com mudanças, devolver ao contribuidor, pedir mudanças ou rejeitar.
   - Mudança grande sempre se pergunta antes.
2. **Adversário antes de opinião.** Cada PR passa por revisores cujo trabalho é
   tentar QUEBRÁ-LO, com evidência. Ler o diff e achar bonito não é revisão.
3. **Validação das recomendações.** O que o revisor concluiu passa por um
   validador que confere na fonte primária (arquivo:linha, `git show`) as
   afirmações que sustentam a recomendação.
   - Para agentes: o advisor; se ele estiver indisponível, um agente
     independente, só leitura.
   - Discordância se resolve na fonte, não no voto.
4. **Nada vai ao GitHub antes de o mantenedor ver tudo pronto**: diffs, testes,
   rascunhos dos comentários.
5. **Mesclar não é deployar.** O deploy é outra decisão, com o procedimento de
   [operations.md, "Atualizar"](operations.md#atualizar). Nunca com prova no
   ar, e perto de um evento só depois de perguntar.

## 1. Levantamento

- `gh pr list`; para cada PR, `gh pr view N` (descrição, commits) e
  `gh pr diff N`.
- **Base do PR × `main` atual.** A base sai dos pais dos commits:
  `gh api repos/bcribas/nutellaboot/pulls/N/commits`.
  - Um PR feito sobre um `main` velho pode ignorar o que mudou desde então: o
    console reescrito, uma regra de acesso, um leitor único.
  - Avalie a aplicabilidade SEMÂNTICA com
    `git diff <base> origin/main -- <arquivos do PR>`, não só com
    `gh pr diff N | git apply --check`.
- **`maintainerCanModify`** (`gh pr view N --json maintainerCanModify`) decide
  onde entram os nossos ajustes (ver [Execução](#4-execução-depois-da-aprovação)).
- **Política já decidida.** Se o PR muda uma decisão registrada, a mudança se
  discute com o mantenedor, não se resolve no código.
  - As invariantes e as armadilhas do `CLAUDE.md` são decisões registradas.
  - Procure o histórico com `git log -S'<termo>'`, e confira se a decisão não
    foi superada depois.
- **PRs que se tocam.** Dois PRs no mesmo arquivo (por exemplo, dois no
  firewall) se revisam juntos, e a integração os testa juntos.

## 2. Revisão adversária

- **Revisores em paralelo**, só leitura, agrupados por tema: servidor, cliente
  de boot, telas, e o PR mais arriscado sozinho.
- **Cada revisor tenta quebrar** e entrega:
  - defeitos confirmados, com arquivo:linha e o caso concreto (entrada → saída
    de antes → saída de agora);
  - o que resistiu ao ataque;
  - o veredito: aplicar / aplicar com mudanças / rejeitar.
- **A lista de conferência é o `CLAUDE.md`**: as 20 invariantes e as
  armadilhas. Os eixos abaixo são os que mais pegam, cada um com o que conferir.

### Acesso

- Rota nova de console usa `auth.require_console` ou `auth.require_admin` e as
  funções de `services/ownership.py`, nunca a checagem de dono à mão. Rota sem
  `Depends` chama `auth.principal`, nunca lê `Authorization` na mão.
- O que é de outro dono responde 404, e sem credencial é 401 (invariante 11).
- O `owner` cru é a credencial do sub-admin: toda resposta passa pelo funil
  `ownership.site_image_para` / `owner_publico` (invariante 18,
  `tests/test_owner_leak.py`).
- Hash de senha, chave e token não saem para quem não precisa: conferir o
  valor na resposta, não o nome do campo.

### Contrato com a máquina já instalada

- Tudo em `client/` vai dentro do initrd ou de uma camada publicada. Rota,
  variável `NB_*`, formato do `/boot/v3/*` (texto puro, invariante 3) e caminho
  `/api/v1/images/...` (invariante 10) continuam valendo para sempre.
- Campo novo de telemetria é opcional nos dois lados: a frota é heterogênea.
- Mudou `client/telemetry/`? O PR sobe o `VERSION`, e a mudança só chega às
  máquinas com a camada nova publicada em todos os modelos e um reboot.
- Mudou o initrd ou o kernel? Precisa de `nb3-build-initrd`, de pendrives
  regerados e de aviso às sedes que bootam por iPXE.

### O caminho de boot (shell do initrd)

- O initrd é busybox: não tem `head`, o `printf "%d"` do awk é de 32 bits, e
  comando externo só existe se o hook o copiar (`tests/test_bootstrap_shell.py`
  roda com um PATH mínimo).
- `sh` POSIX: sem `local`, cada temporário do `05-ui.sh` pertence a uma função
  (invariante 16). Nada de `read` interativo (invariante 5). Mensagem de tela
  em inglês, sem acento, cabendo em 25 linhas (invariante 12).
- Certificado sempre verificado (invariante 6), e a rede é do bootstrap do
  initrd (invariante 7).
- `client/stuff/25-usbupdate.sh` regrava o pendrive: é o arquivo mais perigoso
  do projeto (invariante 19).
- Mudança no caminho de boot se confere num boot de verdade em qemu
  (`tools/nb3-qemu-shot --mem 4G`), não só na suíte.

### Firewall

- O heredoc do `client/stuff/60-postmount.d/30-firewall.sh` substitui, em tempo
  de boot, o script do pacote `maratona-firewall` (que vem assado na camada
  base). Ele tem de ficar idêntico ao arquivo commitado no pacote: conserto no
  script vai para os dois repositórios.
- O nome de cada entrada do allowlist vira nome de arquivo como root no sistema
  montado. A regra do item vem de `config.DITADOS_PELO_PADRAO`.

### API e formulário

- Rota ou campo novo: `docs/api.md` no mesmo commit. Formato de resposta é
  `server/app/schemas.py` (`schemas.DOCS`), nunca `response_model`
  (`tests/test_openapi_shapes.py`). Toda rota citada em `tools/` existe
  (`tests/test_tool_routes.py`).
- O MOJ consome a API com chave de serviço: mudança de contrato se combina com
  ele antes.
- O formulário do modelo se lê por `store.get_schema`, nunca o arquivo
  (há teste que conta os leitores).
- Escrita em disco só por `fsdb` (invariante 1). Evento só por
  `services/eventos.publicar`, nunca segurando `fsdb.locked`.

### Telas

- O console tem três modos: lista, página de detalhe e diálogo
  (`web/common/dialogo.js`, `web/common/acao.js`, `tests/test_console.py`).
- Texto de fora entra por `esc()` ou `textContent`, nunca cru em `innerHTML`.
- Toda string nos três idiomas (invariante 8), toda classe no CSS que a tela
  carrega (`tests/test_web_css.py`), todo id no HTML (`tests/test_web_ids.py`).
- O no-undef caseiro tem limites conhecidos (ver o `CLAUDE.md`): um PR que
  passa nele ainda pode quebrar no navegador.

### Testes

- O PR traz algum? Quebra um existente? Que teste falharia sem ele?
- Comando destrutivo se testa pelo EFEITO (a fila de cada máquina, o estado no
  disco), não pela rota.

## 3. Decisão

- **Um PR por pergunta**, com o achado principal. A opção recomendada vem
  primeiro, e cada opção diz o porquê.
- **As respostas ficam registradas**, junto com a validação.
- **"Rejeitar" também tem o seu racional**, e esse racional vai para o
  comentário do PR.

## 4. Execução (depois da aprovação)

- **Isolamento.** O checkout de desenvolvimento serve o ambiente de teste, então
  nunca troque de branch nele. Use um worktree por PR:
  ```
  git fetch origin
  git worktree add --detach <scratch>/wt-N origin/main
  cd <scratch>/wt-N && gh pr checkout N
  git merge --no-edit origin/main     # o "update branch": nunca rebase nem force-push no fork
  ```
- **A suíte** roda no worktree com o Python do checkout: primeiro
  `ln -s <checkout>/.venv .venv` no worktree (os testes que sobem um servidor
  de verdade ou chamam as ferramentas procuram o `.venv` dentro do
  repositório), depois `.venv/bin/python -m pytest -q`, uns 3 min. Ela importa
  o código do worktree, não o do checkout.
- **Nossos ajustes** entram como commits NOSSOS por cima dos do PR.
  - Mensagem em português, no presente. Ela diz o que o PR já fazia e o que foi
    completado.
  - Rodapé só com `Co-Authored-By` quando houver agente.
- **Testes que discriminam.** Rode os testes novos contra o código do PR SEM os
  nossos commits (`git stash push -- <código>`). Eles têm de falhar lá e passar
  com a correção.
- **Integração:** um worktree com `origin/main` mais `git merge --no-ff` de
  todos os PRs aprovados, e nele a suíte inteira.
- **Tela se confere no navegador**: `tools/nb3-dev` com `NB3_DATA_ROOT`
  temporário, numa porta que não seja a do ambiente de teste, e Firefox
  headless. Recarregue sem cache antes de concluir que algo está errado.
- **Caminho de boot se confere em qemu** (`tools/nb3-qemu-shot --mem 4G`).

## 5. Publicação (só com o OK do mantenedor)

1. **O merge, de um dos dois jeitos:**
   - `maintainerCanModify: true`: push dos nossos commits no branch do PR (o
     `gh pr checkout` já apontou para o fork) e `gh pr merge N --merge`;
   - `maintainerCanModify: false`: o branch do PR, sem mudar nenhum commit
     dele, entra no `main` por `git merge --no-ff`, os nossos commits vão por
     cima, e o push é no `main`. O esperado é que o GitHub marque o PR como
     "Merged" quando o último commit dele fica alcançável a partir do `main`,
     e assim o crédito fica. Isso ainda não foi visto neste repositório:
     confira na primeira vez. Se o GitHub não marcar, ou se o PR precisar ser
     refeito, feche-o com o crédito no comentário, como no #1.
   - Não feche PR que foi incorporado.
2. **Confira que `git diff <integração> origin/main` está VAZIO**: o que foi
   para o `main` é o que foi testado.
3. **Comentários educados e concretos** (arquivo:linha e o porquê), em
   português:
   - **mesclado com ajustes** → resumo do que mudou por cima e por quê;
   - **pedir mudanças** → `gh pr review N --request-changes`, com checklist;
   - **rejeitado** → `gh pr close N --comment …`, com o motivo e o convite para
     uma issue se a ideia puder voltar de outra forma;
   - **como veio** → agradecimento curto dizendo o que foi conferido.
4. **Depois:**
   - `git pull --ff-only` no checkout;
   - remover os worktrees e os branches locais;
   - registrar o que entrou, o que aguarda o contribuidor e o que o deploy vai
     precisar: reiniciar o worker, publicar a camada de telemetria, reconstruir
     o initrd, avisar o MOJ ou as sedes por iPXE.

## Para quem contribui

Um PR entra mais rápido quando:

- **É feito sobre o `main` ATUAL.** Faça rebase antes de abrir: PR sobre `main`
  velho costuma conflitar.
- **Passa na suíte:** `.venv/bin/python -m pytest -q` (ver
  [testing.md](testing.md)).
- **Traz teste** que falha sem a mudança e passa com ela.
- **Respeita as invariantes do [`CLAUDE.md`](../CLAUDE.md).** Mudar uma delas,
  ou uma premissa de produto, se discute antes numa issue.
- **Tem string nova de tela nos três idiomas** (`web/common/locales/`), e
  mensagem do caminho de boot em inglês, sem acento.
- **Atualiza a doc no mesmo commit** quando muda rota, campo ou fluxo:
  [api.md](api.md), [operations.md](operations.md) e as armadilhas do
  `CLAUDE.md`.
- **Mantém os dois lados do contrato com a máquina**: código novo no servidor
  continua servindo o cliente que já está instalado.
- **Não reescreve regra de acesso:** reusa `services/ownership.py`.

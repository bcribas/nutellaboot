# Notas para agentes de IA

Contexto rápido para quem for mexer neste repositório sem tê-lo lido inteiro.

## O que é

Sistema de boot em rede da Maratona SBC de Programação. Máquinas de
laboratório ligam por um pendrive, baixam o sistema operacional do servidor
em camadas squashfs e montam tudo com overlayfs. Durante a prova, o servidor
recebe telemetria e envia comandos (bloquear tela, limpar home, reiniciar).

Três partes: **servidor** (FastAPI, `server/`), **cliente de boot**
(initramfs + shell, `client/`) e **telas web** (JavaScript puro, `web/`).

## Invariantes — quebrar qualquer uma destas causa dano real

1. **Escrita atômica sempre.** Todo acesso ao disco passa por
   `server/app/fsdb.py` (tmp + `os.replace` + `flock`). Nunca escreva direto
   com `open(..., "w")` no diretório `data/`.

2. **O servidor roda com UM único worker uvicorn.** `services/notify.py`
   guarda os sinais de long-poll e SSE em memória do processo. Com dois
   workers, metade dos comandos demoraria os 5 s do mecanismo de segurança em
   vez de chegar na hora, e metade dos painéis não receberia eventos.

3. **`/boot/v3/*` responde texto puro.** Quem consome é shell dentro do
   initramfs, sem `jq`. Não converta essas rotas para JSON.

4. **Camadas extras vêm ANTES no manifest.** A ordem das linhas é a ordem do
   `lowerdir` do overlayfs, e a primeira ganha. Inverter faz a imagem base
   sobrescrever silenciosamente as personalizações.

5. **Nada de `read` interativo no caminho de boot.** Máquina de prova boota
   sozinha; um prompt esperando ENTER trava a sala inteira. Há um teste que
   falha se aparecer (`tests/test_bootstrap_shell.py`).

6. **Certificado sempre verificado.** Nada de `--check-certificate=false`. A
   única exceção é `GET /boot/v3/time`, que existe justamente para acertar o
   relógio e tornar a validação possível. Também há teste para isso.

7. **A rede pertence ao bootstrap do initrd.** O `stuff` servido não pode
   redefinir `configure_localnetwork`/`configure_wifi` — foi exatamente essa
   sobreposição que deixou o wifi morto na versão anterior. Há teste.

8. **Toda string de interface nasce nos três idiomas** (pt, en, es), em
   `web/common/locales/`. Teste compara as chaves dos três arquivos.

9. **O pendrive é liberado cedo.** O initrd copia a configuração para a RAM e
   desmonta antes de qualquer coisa de rede, avisando na tela. Não adicione
   leituras do pendrive depois desse ponto.

10. **`/api/v1/images/...` continua respondendo, para sempre.** O agente de
    telemetria (`client/telemetry/usr/share/mlog/agent.sh`) monta
    `"$NB_SERVER/api/v1/images/$IMAGEROOT"` e esse arquivo vai DENTRO da camada
    squashfs publicada: máquinas já instaladas chamam o caminho antigo, e não
    há como atualizá-las remotamente sem telemetria — que é justamente o que
    quebraria. O alias vive em `LegacyImagePathMiddleware`
    (`server/app/main.py`) e há teste-guarda em `tests/test_legacy_paths.py`.
    O mesmo vale para o contrato de boot (`/boot/v3/*`, `IMAGEROOT`,
    `nutellaboot.conf`, `NB_*`) e para os links já distribuídos
    (`/configureitor/?id=&tk=`).

## Nomenclatura

- **modelo** (`model`, `data/models/<n>/model.json`): o que se configura uma
  vez — camadas (telemetria, wifi, pacotes) e o formulário (`schema.json` com
  os cadeados por campo).
- **site-image** (`data/site-images/<id>/`): a imagem derivada de um modelo,
  uma por sala/sede, com token, chaves e configuração próprias.

O nome antigo era *template*/*image*; a migração está em
`tools/nb3-migrate-names` (idempotente, com `--dry-run`).

## Credenciais (quatro classes)

| Prefixo | Quem usa | Onde fica |
|---|---|---|
| `nb3a_` | administração | hash em `data/keys/admin.json` |
| `nb3s_` | serviços externos (MOJ), com escopos | hash em `data/keys/services.json` |
| `nb3i_` | dono da imagem (configureitor, hotconfig) | `data/images/<id>/token` |
| `nb3m_` | máquina (telemetria, fila de comandos) | `data/images/<id>/machine.key` |
| `nb3b_` | pendrive (endpoints de boot) | `data/images/<id>/boot.key` |

## Comandos

```bash
tools/nb3-dev                      # servidor em 127.0.0.1:8890
.venv/bin/python -m pytest -q      # 105 testes, ~11 s
tools/nb3-seed-testdata            # dados de teste
tools/nb3-layer-worker --check     # confere as ferramentas rootless
```

O ambiente de teste tem um nginx externo que faz proxy de
`https://nutellaboot.charge.naquadah.com.br:8443` para `localhost:8890`.

## Armadilhas já encontradas (não repita)

- `httpx.ASGITransport` **não faz streaming**: executa a aplicação até o fim
  antes de devolver. Testes de SSE precisam de um uvicorn de verdade — veja
  `tests/test_live_server.py`.
- `asyncio.Event` guardado entre requisições quebra quando o loop muda. Os
  eventos são criados dentro da requisição que espera (`notify.py`).
- Módulos ES (`import`) **não carregam por `file://`** (CORS). Os temas da
  tela de bloqueio usam script clássico (`window.NB3Lock`) de propósito.
- `set prefix=($root)` numa imagem GRUB standalone quebra o carregamento de
  módulos (eles vivem no memdisk) e o menu abre vazio, sem erro visível.
- No builder de camadas, a poda e o `mksquashfs` precisam rodar **dentro** do
  mesmo namespace de usuário: os arquivos do apt pertencem a subuids e não
  dão nem para apagar de fora.

## Estilo

Código, comentários, mensagens e documentação em **português do Brasil**.
Comentário só quando explica uma restrição que o código não mostra (por que
algo é assim), nunca narrando o que a linha faz.

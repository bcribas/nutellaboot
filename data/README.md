# data/ — banco-filesystem do NutellaBoot 3

Este diretório é o estado vivo do servidor (imagens, chaves, telemetria, filas).
Nada aqui é versionado — veja `docs/architecture.md` para o esquema completo.

Estrutura criada pelo `tools/nb3-seed-testdata` (teste) ou pela própria API (produção):

```
server.json                     configuração global do servidor
keys/admin.json                 hashes das API keys de administração
keys/services.json              hashes das API keys de serviço (MOJ) com escopos
templates/<nome>/               templates de imagem (camadas + schema de config)
images/<id>/                    uma imagem bootável por diretório
layerbuilds/{queue,running,done,failed}/   fila do builder de camadas
blobs/                          squashfs construídos localmente (servidos em /blobs/)
```

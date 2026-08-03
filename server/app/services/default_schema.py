"""Esquema de configuração padrão das imagens da Maratona.

O esquema é DADO, não código: fica em models/<nome>/schema.json e pode ser
editado. Esta função só constrói o padrão inicial.

Formato de cada campo:
  key       nome da variável que chega ao stuff (maiúsculas)
  type      bool | select | text | password | list
  label/help  dicionários {pt, en, es} — as telas são trilíngues
  options   [{value, label}] para select; para list, as opções disponíveis
  default   valor inicial
  locked    true = só administração altera (o "perfil bloqueado" da maratona)
"""

from __future__ import annotations

try:
    from zoneinfo import available_timezones
except ImportError:  # pragma: no cover
    available_timezones = None


def _tz_options() -> list[dict]:
    if available_timezones is None:
        zones = ["America/Sao_Paulo", "America/Santiago", "America/Mexico_City", "UTC"]
    else:
        zones = sorted(
            z
            for z in available_timezones()
            if z.startswith(("America/", "Atlantic/", "Pacific/")) or z == "UTC"
        )
    return [{"value": z, "label": z} for z in zones]


def _t(pt: str, en: str, es: str) -> dict:
    return {"pt": pt, "en": en, "es": es}


def build_default_schema() -> dict:
    return {
        "version": 1,
        "fields": [
            {
                "key": "ICPC_AUTOLOGIN",
                "type": "bool",
                "default": True,
                "locked": True,
                "label": _t("Login automático", "Automatic login", "Inicio de sesión automático"),
                "help": _t(
                    "Entra direto no usuário icpc ao ligar, sem pedir senha.",
                    "Logs straight into the icpc user at boot, with no password prompt.",
                    "Entra directamente al usuario icpc al arrancar, sin pedir contraseña.",
                ),
            },
            {
                "key": "FORCE_CLEAN_HOME_ON_BOOT",
                "type": "bool",
                "default": False,
                "label": _t("Limpar a home a cada boot", "Clean home on every boot", "Limpiar la home en cada arranque"),
                "help": _t(
                    "Apaga os arquivos do usuário icpc toda vez que a máquina liga. "
                    "Use com cuidado: equivale a rodar limpar-home-agora em todo boot.",
                    "Wipes the icpc user's files every time the machine boots. "
                    "Use with care: same as running clean-home-now on every boot.",
                    "Borra los archivos del usuario icpc cada vez que arranca la máquina. "
                    "Úselo con cuidado: equivale a ejecutar limpiar-home-ahora en cada arranque.",
                ),
            },
            {
                "key": "TIMEZONE",
                "type": "select",
                "default": "America/Sao_Paulo",
                "options": _tz_options(),
                "label": _t("Fuso horário", "Time zone", "Zona horaria"),
                "help": _t(
                    "Fuso horário das máquinas desta sede.",
                    "Time zone for the machines at this site.",
                    "Zona horaria de las máquinas de esta sede.",
                ),
            },
            {
                "key": "INPUT_SOURCES",
                "type": "list",
                "default": ["('xkb','br')", "('xkb','us')", "('xkb','latam')"],
                "options": [
                    {"value": "('xkb','br')", "label": "br"},
                    {"value": "('xkb','us')", "label": "us"},
                    {"value": "('xkb','es')", "label": "es"},
                    {"value": "('xkb','latam')", "label": "latam"},
                    {"value": "('xkb','br+thinkpad')", "label": "br+thinkpad"},
                ],
                "label": _t("Layouts de teclado", "Keyboard layouts", "Distribuciones de teclado"),
                "help": _t(
                    "Ordem dos layouts; o primeiro é o padrão.",
                    "Layout order; the first one is the default.",
                    "Orden de las distribuciones; la primera es la predeterminada.",
                ),
            },
            {
                "key": "LANGUAGE",
                "type": "select",
                "default": "pt",
                "options": [
                    {"value": "pt", "label": "Português"},
                    {"value": "en", "label": "English"},
                    {"value": "es", "label": "Español"},
                ],
                "label": _t("Idioma das telas", "Screen language", "Idioma de las pantallas"),
                "help": _t(
                    "Idioma das mensagens mostradas na máquina (inclusive a tela de bloqueio).",
                    "Language of the messages shown on the machine (including the lock screen).",
                    "Idioma de los mensajes mostrados en la máquina (incluida la pantalla de bloqueo).",
                ),
            },
            {
                "key": "SEEDIMAGE",
                "type": "bool",
                "default": False,
                "label": _t("Semear a imagem (P2P)", "Seed the image (P2P)", "Sembrar la imagen (P2P)"),
                "help": _t(
                    "Esta máquina serve a imagem para as outras da rede local, acelerando o boot da sala.",
                    "This machine serves the image to the others on the local network, speeding up the room's boot.",
                    "Esta máquina sirve la imagen a las demás de la red local, acelerando el arranque de la sala.",
                ),
            },
            {
                "key": "MINRAM",
                "type": "select",
                "default": "8192",
                "locked": True,
                "options": [
                    {"value": "0", "label": "sem mínimo"},
                    {"value": "4096", "label": "4 GB"},
                    {"value": "8192", "label": "8 GB"},
                    {"value": "16384", "label": "16 GB"},
                ],
                "label": _t("RAM mínima", "Minimum RAM", "RAM mínima"),
                "help": _t(
                    "Memória mínima exigida para a máquina bootar.",
                    "Minimum memory required for the machine to boot.",
                    "Memoria mínima requerida para que la máquina arranque.",
                ),
            },
            {
                "key": "DISABLE_FIREWALL",
                "type": "bool",
                "default": False,
                "locked": True,
                "label": _t("Desligar o firewall", "Disable the firewall", "Desactivar el cortafuegos"),
                "help": _t(
                    "O firewall é obrigatório durante a maratona.",
                    "The firewall is mandatory during the contest.",
                    "El cortafuegos es obligatorio durante la maratón.",
                ),
            },
            {
                "key": "FIREWALL_ALLOWLIST",
                "type": "list",
                "default": ["global.naquadah.com.br 177.70.23.143"],
                "locked": True,
                "options": [],
                # o par que o `help` promete. O nome vira NOME DE ARQUIVO no
                # cliente (usr/share/maratona-firewall/hosts/<nome>), então
                # aqui é o lugar de garantir que ele não tem `/` nem `..`
                "item_pattern": r"[A-Za-z0-9][A-Za-z0-9.-]*\s+[0-9a-fA-F.:]+",
                "label": _t("Liberados no firewall", "Firewall allowlist", "Permitidos en el cortafuegos"),
                "help": _t(
                    "Pares \"nome ip\" liberados durante a prova.",
                    'Pairs "hostname ip" allowed during the contest.',
                    'Pares "nombre ip" permitidos durante la prueba.',
                ),
            },
            {
                "key": "DEFAULTBROWSERURL",
                "type": "text",
                "default": "https://moj.naquadah.com.br",
                "locked": True,
                "label": _t("Página inicial do navegador", "Browser home page", "Página inicial del navegador"),
                "help": _t(
                    "Endereço do juiz (MOJ/BOCA) aberto pelo navegador.",
                    "Judge address (MOJ/BOCA) opened by the browser.",
                    "Dirección del juez (MOJ/BOCA) abierta por el navegador.",
                ),
            },
            {
                "key": "ALLOWUSBMOUNT",
                "type": "bool",
                "default": False,
                "locked": True,
                "label": _t("Permitir pendrives", "Allow USB drives", "Permitir memorias USB"),
                "help": _t(
                    "Montagem de dispositivos USB pelos competidores.",
                    "Mounting USB devices by contestants.",
                    "Montaje de dispositivos USB por los competidores.",
                ),
            },
            {
                "key": "ALLOWVM",
                "type": "bool",
                "default": False,
                "locked": True,
                "label": _t("Permitir máquina virtual", "Allow virtual machine", "Permitir máquina virtual"),
                "help": _t(
                    "Se desligado, a imagem se recusa a bootar dentro de virtualização.",
                    "When off, the image refuses to boot inside virtualization.",
                    "Si está apagado, la imagen se niega a arrancar dentro de virtualización.",
                ),
            },
            {
                "key": "ALLOWNETWORKCHANGE",
                "type": "bool",
                "default": False,
                "locked": True,
                "label": _t("Permitir mexer na rede", "Allow network changes", "Permitir cambios de red"),
                "help": _t(
                    "Deixa o competidor reconfigurar a rede.",
                    "Lets the contestant reconfigure networking.",
                    "Permite al competidor reconfigurar la red.",
                ),
            },
            {
                "key": "LOCK_THEME",
                "type": "select",
                "default": "classico",
                "options": [
                    {"value": "classico", "label": "Clássico"},
                    {"value": "animado", "label": "Animado"},
                    {"value": "minimal", "label": "Minimalista"},
                ],
                "label": _t("Tema da tela de bloqueio", "Lock screen theme", "Tema de la pantalla de bloqueo"),
                "help": _t(
                    "Aparência da tela mostrada quando as máquinas são bloqueadas.",
                    "Look of the screen shown when machines are locked.",
                    "Apariencia de la pantalla mostrada cuando las máquinas están bloqueadas.",
                ),
            },
            {
                "key": "LOCK_FALLBACK_PASSWORD",
                "type": "password",
                "default": "",
                "label": _t(
                    "Senha para destravar a tela",
                    "Password to unlock the screen",
                    "Contraseña para desbloquear la pantalla",
                ),
                "help": _t(
                    "Digitada na própria máquina destrava a tela sem depender da rede. "
                    "Guardada só como hash; deixe em branco para manter a atual.",
                    "Typed on the machine itself, unlocks the screen without needing the network. "
                    "Stored only as a hash; leave blank to keep the current one.",
                    "Escrita en la propia máquina, desbloquea la pantalla sin depender de la red. "
                    "Guardada solo como hash; déjela en blanco para mantener la actual.",
                ),
            },
        ],
    }

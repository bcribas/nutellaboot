# shellcheck shell=sh
# O pendrive se atualiza sozinho quando fica para trás.
#
# Até aqui nada avisava que o pendrive estava velho: o sintoma era a tela
# "NO IMAGE" (initrd antigo lendo o formato novo do nutellaboot.conf), ou pior,
# um boot que funciona mas sem as correções da semana. Quem grava 45 pendrives
# não regrava 45 pendrives por causa de uma linha.
#
# REGRAS DESTE ARQUIVO, todas aprendidas doendo:
#
#   * a checagem NÃO tem poder de veto. Servidor fora do ar, resposta estranha,
#     initrd sem carimbo — segue o boot. Enfeite não derruba sala;
#   * o pendrive só é tocado depois de os arquivos novos estarem no disco local
#     E com o md5 conferido. A partição tem ~399 MB e o conteúdo 202: não cabem
#     os dois pares, então os antigos precisam sair antes dos novos entrarem, e
#     essa é a única janela em que o pendrive fica sem boot;
#   * uma tentativa por versão, marcada no disco local. Sem isso, um pendrive
#     protegido contra escrita reinicia a máquina para sempre;
#   * nutellaboot.conf e wifi.conf são da sede, não nossos. Não se toca.

NB_USB_MNT=${NB_USB_MNT:-/nb3usb}

# Lê a resposta de /boot/v3/<img>/usb. Devolve 0 só quando ela faz sentido.
nb_usb_server_build() {
    _uu_resp=$(nb_get "$NB_SERVER/boot/v3/$IMAGEROOT/usb" 2> /dev/null) || return 1
    [ -n "$_uu_resp" ] || return 1
    NB_USB_BUILD=$(printf '%s\n' "$_uu_resp" | sed -n 's/^BUILD //p' | sed -n 1p)
    [ -n "$NB_USB_BUILD" ] || return 1
    [ "$NB_USB_BUILD" = unknown ] && return 1
    # as demais linhas vêm no formato do manifest de camadas: MD5 ARQUIVO URL
    NB_USB_FILES=$(printf '%s\n' "$_uu_resp" | sed -n '/^BUILD /!p')
    [ -n "$NB_USB_FILES" ]
}

# Acha a partição de configuração. Ela foi desmontada no início do boot (o
# pendrive pode ter sido retirado desde então — o boot manda retirar), então
# procurar de novo é a única forma de saber se ainda está aqui.
nb_usb_device() {
    _uu_try=0
    while [ "$_uu_try" -lt "${NB_USB_TRIES:-3}" ]; do
        _uu_dev=$(blkid -L NB3CFG 2> /dev/null)
        if [ -n "$_uu_dev" ]; then
            printf '%s' "$_uu_dev"
            return 0
        fi
        sleep "${NB_USB_WAIT:-2}"
        _uu_try=$((_uu_try + 1))
    done
    return 1
}

nb_usb_sem_pendrive_screen() {
    nb_fatal_screen "OLD USB" \
        "!This computer booted from an out-of-date USB drive," \
        "!and the drive is no longer plugged in." \
        "" \
        "Site:   $IMAGEROOT" \
        "On the drive: ${NB_INITRD_BUILD:-unknown}" \
        "On the server: $NB_USB_BUILD" \
        "" \
        "!What to do:" \
        "  1. Plug the USB drive back in and turn this computer on again." \
        "     It updates itself, with no keyboard, and reboots." \
        "  2. Or write a fresh drive: the image is in the console of" \
        "     this site, under 'pendrive de boot'." \
        "" \
        "The same drive works for every site - only nutellaboot.conf changes."
}

nb_usb_falhou_screen() {
    nb_fatal_screen "USB FAILED" \
        "!The USB drive could not be updated." \
        "" \
        "Reason: $1" \
        "Site:   $IMAGEROOT" \
        "" \
        "!What to do:" \
        "  1. The drive may be write-protected: some models have a small" \
        "     switch on the side." \
        "  2. Write a fresh drive with the image from the console of this" \
        "     site, under 'pendrive de boot'." \
        "" \
        "This computer will not try again by itself for this version."
}

# Baixa e confere ANTES de tocar no pendrive: quando os arquivos velhos saírem,
# os novos já têm que estar bons e locais.
nb_usb_stage() {
    _uu_dir=$1
    rm -rf "$_uu_dir"
    mkdir -p "$_uu_dir"
    printf '%s\n' "$NB_USB_FILES" | while read -r _uu_md5 _uu_file _uu_urls; do
        [ -z "$_uu_file" ] && continue
        NB_DL_PROGRESS=1
        NB_DL_LABEL="USB update: $_uu_file"
        export NB_DL_PROGRESS NB_DL_LABEL
        # shellcheck disable=SC2086
        nb_download "$_uu_dir/$_uu_file" 4 $_uu_urls || exit 1
        NB_DL_PROGRESS=0
        NB_DL_LABEL=
        nutella_md5sum "$_uu_md5" "$_uu_dir/$_uu_file" || exit 1
    done
}

# A janela de risco. Curta de propósito, e só depois de tudo conferido.
nb_usb_grava() {
    _uu_dir=$1
    _uu_dev=$2
    mkdir -p "$NB_USB_MNT"
    mount "$_uu_dev" "$NB_USB_MNT" 2> /dev/null || return 1
    for _uu_f in vmlinuz initrd.img; do
        rm -f "$NB_USB_MNT/$_uu_f"
    done
    sync
    for _uu_f in vmlinuz initrd.img; do
        log_begin_msg "Writing $_uu_f to the USB drive"
        if ! cp "$_uu_dir/$_uu_f" "$NB_USB_MNT/$_uu_f"; then
            log_failure_msg "could not write $_uu_f"
            umount "$NB_USB_MNT" 2> /dev/null
            return 1
        fi
        log_end_msg
    done
    sync
    umount "$NB_USB_MNT" 2> /dev/null
    return 0
}

nb_usb_update() {
    # sem carimbo não há o que comparar (initrd anterior a esta mudança), e
    # `nousbupdate=y` na linha de comando é a escotilha para o dia em que a
    # prova já começou e não dá para esperar um reinício
    [ -z "${NB_INITRD_BUILD:-}" ] && return 0
    [ "${nousbupdate:-}" = y ] && return 0

    nb_usb_server_build || return 0
    [ "$NB_USB_BUILD" = "$NB_INITRD_BUILD" ] && return 0

    nb_warn "this USB drive is out of date (${NB_INITRD_BUILD} -> ${NB_USB_BUILD})"

    # Uma tentativa de ESCRITA por versão. O marcador vive no disco local, que
    # sobrevive ao reinício: sem ele, um pendrive que não aceita escrita
    # reinicia a máquina para sempre.
    _uu_marca=$STORAGEDIR/.usbupd-tried
    if [ "$(cat "$_uu_marca" 2> /dev/null)" = "$NB_USB_BUILD" ]; then
        nb_usb_falhou_screen "already tried once for this version"
    fi

    _uu_dev=$(nb_usb_device) || nb_usb_sem_pendrive_screen

    nb_screen "USB UPDATE" \
        "!This USB drive is out of date and is being updated now." \
        "" \
        "Do not turn the computer off and do not remove the drive." \
        "It reboots by itself when it finishes." \
        "" \
        "On the drive: $NB_INITRD_BUILD" \
        "On the server: $NB_USB_BUILD"

    # Falha de download NÃO condena o pendrive: nada foi tocado ainda, e uma
    # queda de rede é transitória. Segue o boot com o initrd velho, que é o que
    # a máquina faria de qualquer forma, e tenta de novo no próximo. (Marcar
    # aqui foi a primeira versão disto, e teria transformado um blip de rede em
    # máquina condenada.)
    if ! nb_usb_stage "$STORAGEDIR/usbupd"; then
        nb_warn "the new boot files could not be downloaded - keeping the old USB drive"
        rm -rf "$STORAGEDIR/usbupd"
        return 0
    fi

    # Daqui para baixo é irreversível: os arquivos antigos saem do pendrive
    # para os novos caberem. A marca é gravada ANTES, porque o que ela protege
    # é justamente a repetição desta parte.
    mkdir -p "$STORAGEDIR"
    echo "$NB_USB_BUILD" > "$_uu_marca"
    sync

    nb_usb_grava "$STORAGEDIR/usbupd" "$_uu_dev" || nb_usb_falhou_screen "writing to the drive failed"
    rm -rf "$STORAGEDIR/usbupd"
    rm -f "$_uu_marca"
    sync

    nb_screen "REBOOTING" \
        "!The USB drive was updated." \
        "" \
        "This computer is restarting to use it. Nothing else to do." \
        "" \
        "New version: $NB_USB_BUILD"
    sleep "${NB_USB_REBOOT_WAIT:-8}"
    reboot -f
    # se o reboot não pegar, parar aqui é melhor que seguir: o pendrive agora
    # tem o initrd novo e esta máquina ainda está rodando o velho. Mesmo
    # idioma do nb_fatal (00-header.sh).
    panic=60 panic "the USB drive was updated but the machine did not restart"
}

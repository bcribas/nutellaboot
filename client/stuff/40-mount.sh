# shellcheck shell=sh
# Montagem do root (overlayfs sobre as camadas squashfs), home persistente e swap.

mount_layers() {
    for mod in squashfs overlay loop ahci ext4 fuse virtio_blk virtio_net nvme sd_mod; do
        modprobe "$mod" 2>/dev/null
    done
    wait_for_udev 10

    PATH="$PATH:/usr/bin"
    nutella_findblock
    [ -z "$possibledisks" ] && nb_fatal "Nenhum disco utilizável. Se a máquina só tem NTFS, faça um desligamento completo do Windows"

    _ok=0
    for disk in $possibledisks; do
        nb_warn "usando $disk"
        FSTYPE=ext4
        if ! mount "$disk" "$BLOCKROOT" 2>/dev/null; then
            FSTYPE=ntfs
            mount -t ntfs -o permissions "$disk" "$BLOCKROOT" 2>/dev/null || continue
        fi
        mkdir -p "$STORAGEDIR"
        if nb_retry "${NB_MANIFEST_TRIES:-10}" 10 download_boot_files "$STORAGEDIR"; then
            _ok=1
            break
        fi
        umount "$BLOCKROOT" 2>/dev/null
    done
    [ "$_ok" = 1 ] || nb_fatal "Não foi possível baixar as camadas do sistema"

    _lower=/dev/newroot/lower
    _upper=/dev/newroot/upper
    _work=/dev/newroot/work
    _schema=""
    mkdir -p "$_lower" "$_upper" "$_work"

    while read -r MD5 FILE URLS; do
        [ -z "$FILE" ] && continue
        log_begin_msg "Preparando $FILE"
        mkdir -p "$_lower/$FILE"
        mount -o suid "$STORAGEDIR/$FILE" "$_lower/$FILE" || nb_fatal "não foi possível montar $FILE"
        _schema="$_schema:$_lower/$FILE"
        log_end_msg
    done < "$STORAGEDIR/fstab.nutella"

    log_begin_msg "Montando o sistema de arquivos raiz"
    mount -t overlay overlay -o suid \
        -olowerdir="${_schema#:}",upperdir="$_upper",workdir="$_work" "${rootmnt?}" ||
        nb_fatal "não foi possível montar o overlay"
    log_end_msg
}

mount_persistenthome() {
    _home=$STORAGEDIR/home-$IMAGEROOT.ext4
    [ "$cleanhome" = y ] && rm -rf "$STORAGEDIR"/home-"$IMAGEROOT"*

    if [ -e "$_home" ] && mount "$_home" "${rootmnt?}/home/"; then
        nb_log "home persistente montada"
        return 0
    fi
    [ -e "$_home" ] && mv "$_home" "$_home.old"

    if [ "$FSTYPE" = ntfs ]; then
        # NTFS não suporta o arquivo de imagem com segurança: usa diretório.
        mkdir -p "$STORAGEDIR/home-$IMAGEROOT.insecure"
        mount --bind "$STORAGEDIR/home-$IMAGEROOT.insecure" "${rootmnt?}/home" &&
            nb_log "home em diretório (NTFS)" && return 0
    fi

    log_begin_msg "Criando home persistente (20G)"
    if fallocate -x -l 20g "$_home" &&
        mke2fs.good -t ext4 -q "$_home" &&
        mount "$_home" "${rootmnt?}/home/"; then
        chmod 600 "$_home"
        log_end_msg
        return 0
    fi
    nb_warn "seguindo SEM home persistente (dados serão perdidos no reboot)"
    return 1
}

createandactivateswap() {
    _swap=$STORAGEDIR/swapfile
    log_begin_msg "Preparando swap em disco"
    if [ ! -e "$_swap" ]; then
        fallocate -x -l 2g "$_swap" || {
            nb_warn "não foi possível criar swap"
            return 1
        }
        chmod 600 "$_swap"
    fi
    mkswap "$_swap" > /dev/null && "${rootmnt?}/sbin/swapon" "$_swap"
    log_end_msg
}

createzramswap() {
    mkdir -p "${rootmnt?}/etc/rc.local.d"
    cat > "${rootmnt?}/etc/rc.local.d/swapon" << 'EOF'
#!/bin/bash
modprobe zram
zramctl /dev/zram0 -s 3G -a zstd
mkswap /dev/zram0
swapon -p 10 /dev/zram0
EOF
    chmod a+x "${rootmnt?}/etc/rc.local.d/swapon"
}

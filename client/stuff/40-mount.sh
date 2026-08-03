# shellcheck shell=sh
# Montagem do root (overlayfs sobre as camadas squashfs), home persistente e swap.

mount_layers() {
    for mod in squashfs overlay loop ahci ext4 fuse virtio_blk virtio_net nvme sd_mod; do
        modprobe "$mod" 2>/dev/null
    done
    wait_for_udev 10

    PATH="$PATH:/usr/bin"
    nutella_findblock
    [ -z "$possibledisks" ] && nb_no_disk_screen

    _ok=0
    for disk in $possibledisks; do
        nb_warn "using $disk"
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
    [ "$_ok" = 1 ] || nb_fatal_screen "NO SYSTEM" \
        "!The system could not be downloaded." \
        "" \
        "A disk was found, but the system layers did not arrive from the" \
        "server, or arrived corrupted (the checksum did not match)." \
        "" \
        "Server: $NB_SERVER" \
        "Image:  $IMAGEROOT" \
        "" \
        "!What to check, in this order:" \
        "  1. Is the network cable connected on this machine?" \
        "  2. Are the other machines in the room booting?" \
        "     If they are, this one probably has a bad cable or port." \
        "  3. Is the room's internet link up?" \
        "  4. Ask the site coordinator to open the lab panel and look" \
        "     for this machine."

    _lower=/dev/newroot/lower
    _upper=/dev/newroot/upper
    _work=/dev/newroot/work
    _schema=""
    mkdir -p "$_lower" "$_upper" "$_work"

    while read -r MD5 FILE URLS; do
        [ -z "$FILE" ] && continue
        log_begin_msg "Preparing $FILE"
        mkdir -p "$_lower/$FILE"
        mount -o suid "$STORAGEDIR/$FILE" "$_lower/$FILE" || nb_fatal "could not mount $FILE"
        _schema="$_schema:$_lower/$FILE"
        log_end_msg
    done < "$STORAGEDIR/fstab.nutella"

    log_begin_msg "Mounting the root filesystem"
    mount -t overlay overlay -o suid \
        -olowerdir="${_schema#:}",upperdir="$_upper",workdir="$_work" "${rootmnt?}" ||
        nb_fatal "could not mount the overlay"
    log_end_msg
}

mount_persistenthome() {
    _home=$STORAGEDIR/home-$IMAGEROOT.ext4
    [ "$cleanhome" = y ] && rm -rf "$STORAGEDIR"/home-"$IMAGEROOT"*

    if [ -e "$_home" ] && mount "$_home" "${rootmnt?}/home/"; then
        nb_log "persistent home mounted"
        return 0
    fi
    [ -e "$_home" ] && mv "$_home" "$_home.old"

    if [ "$FSTYPE" = ntfs ]; then
        # NTFS não suporta o arquivo de imagem com segurança: usa diretório.
        mkdir -p "$STORAGEDIR/home-$IMAGEROOT.insecure"
        mount --bind "$STORAGEDIR/home-$IMAGEROOT.insecure" "${rootmnt?}/home" &&
            nb_log "home stored as a directory (NTFS)" && return 0
    fi

    log_begin_msg "Creating persistent home (20G)"
    if fallocate -x -l 20g "$_home" &&
        mke2fs.good -t ext4 -q "$_home" &&
        mount "$_home" "${rootmnt?}/home/"; then
        chmod 600 "$_home"
        log_end_msg
        return 0
    fi
    nb_warn "continuing WITHOUT a persistent home - files will be lost on reboot"
    return 1
}

createandactivateswap() {
    _swap=$STORAGEDIR/swapfile
    log_begin_msg "Preparing swap on disk"
    if [ ! -e "$_swap" ]; then
        fallocate -x -l 2g "$_swap" || {
            nb_warn "could not create the swap file"
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

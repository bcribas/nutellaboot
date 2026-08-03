# shellcheck shell=sh
# Descoberta de disco local e checagens de pré-montagem.

NB_MIN_FREE_KB=${NB_MIN_FREE_KB:-14971520} # ~14,3 GB

# Procura uma partição ext3/ext4/ntfs gravável com espaço suficiente.
# Resultado em $possibledisks (ext4 na frente; partição já usada vence tudo).
nutella_findblock() {
    possibledisks=
    : > /tmp/diskslog
    log_begin_msg "Looking for local storage"
    for disk in /dev/nvme*n*p* /dev/sd?? /dev/vd?? /dev/mmcblk*p*; do
        [ -e "$disk" ] || continue
        fstype=$(/sbin/blkid --probe -s TYPE -o value "$disk" 2>/dev/null)
        case "$fstype" in
            ext3 | ext4 | ntfs) ;;
            *)
                echo "$disk|$fstype|unsupported filesystem" >> /tmp/diskslog
                continue
                ;;
        esac

        mountopts=$fstype
        [ "$fstype" = ntfs ] && mountopts="$fstype -o remove_hiberfile"
        # shellcheck disable=SC2086
        if ! mount -t $mountopts "$disk" "$BLOCKROOT" 2>/dev/null; then
            echo "$disk|$fstype|could not be mounted" >> /tmp/diskslog
            continue
        fi

        if ! touch "$BLOCKROOT/ml-test" 2>/dev/null; then
            echo "$disk|$fstype|mounted read-only" >> /tmp/diskslog
            umount "$BLOCKROOT"
            continue
        fi
        rm -f "$BLOCKROOT/ml-test"

        # `awk END` e não `| tail -n1 | awk`: `tail` tem a mesma chance de
        # não existir no initrd que o `head` não tinha — e a falha seria a
        # mesma, muda, com o espaço livre voltando vazio
        free=$(df "$BLOCKROOT" | awk 'END {print $4}')
        if [ -d "$STORAGEDIR" ] && [ "$factoryreset" = y ]; then
            nb_warn "removing nutellaboot from $disk"
            rm -rf "$STORAGEDIR"
        fi
        if [ -d "$STORAGEDIR" ]; then
            echo "$disk|$fstype|already used before - reusing" >> /tmp/diskslog
            possibledisks=$disk
            umount "$BLOCKROOT"
            break
        fi
        if [ "$free" -gt "$NB_MIN_FREE_KB" ]; then
            echo "$disk|$fstype|$((free / 1024)) MB free - usable" >> /tmp/diskslog
            if [ "$fstype" = ext4 ]; then
                possibledisks="$disk $possibledisks"
            else
                possibledisks="$possibledisks $disk"
            fi
        else
            echo "$disk|$fstype|only $((free / 1024)) MB free, needs $((NB_MIN_FREE_KB / 1024)) MB" >> /tmp/diskslog
        fi
        umount "$BLOCKROOT"
    done
    log_end_msg
    nb_disk_table
}

# Tabela do que foi encontrado. O formato do diskslog é "dispositivo|tipo|
# motivo" justamente para poder ser alinhado aqui e classificado no
# nb_disk_advice — antes era texto solto que só servia para leitura humana.
nb_disk_table() {
    if [ ! -s /tmp/diskslog ]; then
        nb_ui_dim "    no partition was detected on this machine"
        return 0
    fi
    _nbd_max=${1:-4}
    _nbd_n=0
    while IFS='|' read -r _nbd_dev _nbd_fs _nbd_why; do
        [ -n "$_nbd_dev" ] || continue
        _nbd_n=$((_nbd_n + 1))
        if [ "$_nbd_n" -ge "$_nbd_max" ]; then
            nb_ui_dim "    ... and more (the full list is printed above)"
            break
        fi
        printf '    %-18s %-10s %s\n' "$_nbd_dev" "$_nbd_fs" "$_nbd_why"
    done < /tmp/diskslog
}

# Escolhe a causa mais provável e o que fazer. A ordem importa: NTFS que não
# monta é quase sempre o Fast Startup do Windows, e é o caso que mais aparece
# em sala — hibernar deixa o sistema de arquivos travado, e a máquina não tem
# como saber disso sozinha.
nb_disk_advice() {
    if grep -qE '\|ntfs\|(could not be mounted|mounted read-only)' /tmp/diskslog 2>/dev/null; then
        nb_ui_text "Most likely cause: WINDOWS FAST STARTUP"
        nb_ui_dim "Windows was hibernated, not shut down, so the disk stays locked."
        nb_ui_dim "  1. Start Windows and run:  shutdown /s /t 0"
        nb_ui_dim "  2. Turn Fast Startup off in Control Panel > Power Options"
    elif grep -q '|only ' /tmp/diskslog 2>/dev/null; then
        nb_ui_text "Most likely cause: NOT ENOUGH FREE SPACE"
        nb_ui_dim "A disk was found, but none has $(((NB_MIN_FREE_KB + 1048575) / 1048576)) GB free."
        nb_ui_dim "Free up space on the partition above, or use another machine."
    elif [ ! -s /tmp/diskslog ]; then
        nb_ui_text "Most likely cause: THE DISK WAS NOT DETECTED AT ALL"
        nb_ui_dim "This usually means the controller is in RAID / Intel RST mode."
        nb_ui_dim "  1. Enter the BIOS/UEFI setup (F2, F10 or DEL at power on)"
        nb_ui_dim "  2. Set the SATA/NVMe controller mode to AHCI, then save"
    else
        nb_ui_text "Most likely cause: NO SUPPORTED FILESYSTEM"
        nb_ui_dim "Only ext3, ext4 and NTFS work. A BitLocker-encrypted partition"
        nb_ui_dim "also shows up like this, because it cannot be read."
        nb_ui_dim "  -> turn BitLocker off, or add an unencrypted partition"
    fi
}

# A tela que a sala inteira precisa entender sem ajuda.
nb_no_disk_screen() {
    # O orçamento é de 25 linhas (console VGA texto). Passar disso rola a
    # tela e joga o banner para fora — que foi exatamente o que apareceu na
    # primeira verificação em VM. Há teste medindo isso.
    nb_screen "NO DISK" \
        "!This computer has no disk where the system can be stored." \
        "" \
        "The system needs a local partition with $(((NB_MIN_FREE_KB + 1048575) / 1048576)) GB FREE." \
        "Windows is NOT erased and your files are NOT touched." \
        "" \
        "!What was found on this machine:"
    nb_disk_table 4
    printf '\n'
    nb_disk_advice
    _nbd_wait=$(nb_screen_wait)
    printf '\n'
    nb_ui_text "This machine will restart in ${_nbd_wait} seconds."
    sleep "$_nbd_wait"
    reboot -f
    panic=60 panic "no usable disk"
}

checkforvirtualization() {
    [ "$ALLOWVM" = t ] && return 0
    _virt=0
    dmesg | grep -q "bare hardware" || _virt=1
    grep -q hypervisor /proc/cpuinfo && _virt=1
    [ -e /dev/vda ] && _virt=1
    [ "$_virt" = 1 ] && nb_fatal_screen "NO VM" \
        "!This image only runs on real hardware." \
        "" \
        "A virtual machine was detected, and this image is configured to" \
        "refuse them. During a contest this keeps the exam environment" \
        "identical on every machine." \
        "" \
        "!If this IS a real machine:" \
        "  -> ask the site coordinator to allow virtual machines in the" \
        "     image settings (option \"Allow virtual machines\")."
    return 0
}

checkminram() {
    [ -z "$MINRAM" ] && return 0
    [ "$MINRAM" = 0 ] && return 0
    _cur=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
    if [ "$MINRAM" -gt $((_cur * 120 / 100)) ]; then
        nb_fatal_screen "LOW RAM" \
            "!This machine does not have enough memory." \
            "" \
            "Installed:  ${_cur} MB" \
            "Required:   ${MINRAM} MB" \
            "" \
            "The system runs from memory, so a machine below the minimum" \
            "would freeze in the middle of the contest instead of failing" \
            "now." \
            "" \
            "!What to do:" \
            "  -> use another machine, or add memory to this one" \
            "  -> if the memory was just added, check that it is seated" \
            "     properly: the BIOS may be seeing only one module"
    fi
    nb_log "RAM: ${_cur} MB (minimum ${MINRAM} MB)"
}

runpremountconfigs() {
    if [ "$factoryreset" = y ]; then
        nutella_findblock
        nb_fatal_screen "REMOVED" \
            "!NutellaBoot has been removed from this machine." \
            "" \
            "The downloaded system, the persistent home and the swap file" \
            "were all deleted from the local disk. Windows and your own" \
            "files were not touched." \
            "" \
            "!What to do:" \
            "  -> take the USB drive out NOW if you do not want NutellaBoot" \
            "     to install itself again on the next boot" \
            "  -> leave it in if you meant to start over from scratch"
    fi
    checkforvirtualization
    checkminram
}

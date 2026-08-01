# shellcheck shell=sh
# Descoberta de disco local e checagens de pré-montagem.

NB_MIN_FREE_KB=${NB_MIN_FREE_KB:-14971520} # ~14,3 GB

# Procura uma partição ext3/ext4/ntfs gravável com espaço suficiente.
# Resultado em $possibledisks (ext4 na frente; partição já usada vence tudo).
nutella_findblock() {
    possibledisks=
    : > /tmp/diskslog
    log_begin_msg "Procurando armazenamento local"
    for disk in /dev/nvme*n*p* /dev/sd?? /dev/vd?? /dev/mmcblk*p*; do
        [ -e "$disk" ] || continue
        fstype=$(/sbin/blkid --probe -s TYPE -o value "$disk" 2>/dev/null)
        case "$fstype" in
            ext3 | ext4 | ntfs) ;;
            *)
                echo "$disk: tipo $fstype ignorado" >> /tmp/diskslog
                continue
                ;;
        esac

        mountopts=$fstype
        [ "$fstype" = ntfs ] && mountopts="$fstype -o remove_hiberfile"
        # shellcheck disable=SC2086
        if ! mount -t $mountopts "$disk" "$BLOCKROOT" 2>/dev/null; then
            echo "$disk: $fstype, não montou" >> /tmp/diskslog
            continue
        fi

        if ! touch "$BLOCKROOT/ml-test" 2>/dev/null; then
            echo "$disk: $fstype, somente leitura" >> /tmp/diskslog
            umount "$BLOCKROOT"
            continue
        fi
        rm -f "$BLOCKROOT/ml-test"

        free=$(df "$BLOCKROOT" | tail -n1 | awk '{print $4}')
        if [ -d "$STORAGEDIR" ] && [ "$factoryreset" = y ]; then
            nb_warn "removendo nutellaboot de $disk"
            rm -rf "$STORAGEDIR"
        fi
        if [ -d "$STORAGEDIR" ]; then
            echo "$disk: $fstype, já usado antes — reaproveitando" >> /tmp/diskslog
            possibledisks=$disk
            umount "$BLOCKROOT"
            break
        fi
        if [ "$free" -gt "$NB_MIN_FREE_KB" ]; then
            echo "$disk: $fstype, $((free / 1024)) MB livres — candidato" >> /tmp/diskslog
            if [ "$fstype" = ext4 ]; then
                possibledisks="$disk $possibledisks"
            else
                possibledisks="$possibledisks $disk"
            fi
        else
            echo "$disk: $fstype, só $((free / 1024)) MB livres — insuficiente" >> /tmp/diskslog
        fi
        umount "$BLOCKROOT"
    done
    log_end_msg
    echo "===== discos ====="
    cat /tmp/diskslog
    echo "=================="
}

checkforvirtualization() {
    [ "$ALLOWVM" = t ] && return 0
    _virt=0
    dmesg | grep -q "bare hardware" || _virt=1
    grep -q hypervisor /proc/cpuinfo && _virt=1
    [ -e /dev/vda ] && _virt=1
    [ "$_virt" = 1 ] && nb_fatal "Maratona Linux deve rodar em hardware real (virtualização bloqueada)"
    return 0
}

checkminram() {
    [ -z "$MINRAM" ] && return 0
    [ "$MINRAM" = 0 ] && return 0
    _cur=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
    if [ "$MINRAM" -gt $((_cur * 120 / 100)) ]; then
        nb_fatal "Esta máquina tem ${_cur} MB de RAM; o mínimo exigido é ${MINRAM} MB"
    fi
    nb_log "RAM: ${_cur} MB (mínimo ${MINRAM} MB)"
}

runpremountconfigs() {
    if [ "$factoryreset" = y ]; then
        nutella_findblock
        nb_fatal "NutellaBoot removido do disco. Retire o pendrive se não quiser reinstalar"
    fi
    checkforvirtualization
    checkminram
}

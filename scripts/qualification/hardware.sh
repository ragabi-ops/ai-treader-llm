#!/usr/bin/env bash
# Read-only target-host evidence capture. Run as root and keep output out of Git.
set -euo pipefail

permitted_disk='/dev/sda'
permitted_data_partition='/dev/sda1'
permitted_root_partition='/dev/sda3'

if (( EUID != 0 )); then
  printf 'error: run with sudo; DIMM and SMART evidence require root\n' >&2
  exit 2
fi

for command in date dmidecode findmnt hostname lsblk nvidia-smi smartctl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'error: required command is unavailable: %s\n' "$command" >&2
    exit 2
  fi
done

# Inspect mount metadata only. Never open, probe, or enumerate either Windows disk.
if grep -Eq '/dev/nvme(0n1|1n1)' /proc/self/mounts; then
  printf 'error: a Windows-owned NVMe device is mounted; refusing capture\n' >&2
  exit 2
fi

root_source=$(findmnt -nro SOURCE /)
data_source=$(findmnt -nro SOURCE /data)
if [[ "$root_source" != "$permitted_root_partition" ]]; then
  printf 'error: expected / on %s, found %s\n' "$permitted_root_partition" "$root_source" >&2
  exit 2
fi
if [[ "$data_source" != "$permitted_data_partition" ]]; then
  printf 'error: expected /data on %s, found %s\n' "$permitted_data_partition" "$data_source" >&2
  exit 2
fi

section() {
  printf '\n=== %s ===\n' "$1"
}

section 'capture'
printf 'schema_version=1\n'
printf 'captured_at='; date -u +%Y-%m-%dT%H:%M:%SZ
printf 'hostname='; hostname
printf 'permitted_disk=%s\n' "$permitted_disk"
printf 'windows_nvme_policy=metadata-only mount check; no device opened or probed\n'

section 'memory topology'
dmidecode --type 16 --type 17

section 'firmware power-supply record'
# Consumer motherboards commonly omit SMBIOS type 39. An empty section means the
# PSU label, wattage, and GPU cabling still require a physical operator record.
dmidecode --type 39

section 'permitted disk identity and mounts'
lsblk --bytes --json \
  --output NAME,KNAME,PATH,TYPE,SIZE,FSTYPE,FSVER,MOUNTPOINTS,MODEL,SERIAL,TRAN,ROTA,RO \
  "$permitted_disk"
findmnt --json --bytes --output SOURCE,FSTYPE,OPTIONS,SIZE,USED,AVAIL,TARGET /
findmnt --json --bytes --output SOURCE,FSTYPE,OPTIONS,SIZE,USED,AVAIL,TARGET /data

section 'permitted ext4 runtime counters'
for partition in sda1 sda3; do
  for counter in errors_count warning_count msg_count lifetime_write_kbytes; do
    path="/sys/fs/ext4/${partition}/${counter}"
    if [[ -r "$path" ]]; then
      printf '%s.%s=' "$partition" "$counter"
      tr -d '\n' < "$path"
      printf '\n'
    else
      printf '%s.%s=unavailable\n' "$partition" "$counter"
    fi
  done
done

section 'permitted disk SMART'
set +e
smartctl --device=sat --xall --json=o "$permitted_disk"
smart_status=$?
set -e
printf 'smartctl_exit_status=%s\n' "$smart_status"

section 'non-storage temperatures'
# Explicit chip selectors prevent sensors(1) from querying the Windows NVMe drives.
if command -v sensors >/dev/null 2>&1; then
  sensors 'k10temp-*' 'gigabyte_wmi-*' || true
else
  printf 'sensors=unavailable\n'
fi

section 'gpu cooling power and throttle state'
nvidia-smi -q -d PERFORMANCE,TEMPERATURE,POWER

printf '\nCapture complete. SMART is observational only; review its bitmask, warnings, '
printf 'vendor-specific attributes, and USB-bridge limitations explicitly.\n'

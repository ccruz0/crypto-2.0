#!/usr/bin/env bash
# Unified SSH key/options for all scripts

# Always use id_rsa (non-interactive) and strict host key options.
#
# IMPORTANT:
# Do NOT use `eval` for ssh/scp invocation. It breaks commands containing shell operators
# (e.g. `&&`) and can execute parts locally instead of remotely.
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"

# Keep a string form for scripts that may embed it (e.g. rsync -e "...").
SSH_OPTS_STR="-i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

# Array form for safe argument passing.
SSH_OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)

# Helper wrappers (optional)
ssh_cmd() {
  # Usage: ssh_cmd user@host "command"
  ssh "${SSH_OPTS[@]}" "$@"
}

scp_cmd() {
  # Usage: scp_cmd source user@host:dest
  scp "${SSH_OPTS[@]}" "$@"
}

rsync_cmd() {
  # Usage: rsync_cmd local/ user@host:remote/
  # 
  # Permission handling:
  # - Normalizes file permissions: files 644, directories 755
  # - Ensures files are readable by containers and host users
  # - Preserves ownership but makes permissions safe for Docker volumes
  rsync -avz \
    --chmod=Du=rwx,go=rx,Fu=rw,go=r \
    -e "ssh $SSH_OPTS_STR" "$@"
}



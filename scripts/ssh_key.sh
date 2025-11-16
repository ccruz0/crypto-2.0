#!/usr/bin/env bash
# Unified SSH key/options for all scripts

# Always use id_rsa (non-interactive) and strict host key options
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
SSH_OPTS="-i \"$SSH_KEY\" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

# Helper wrappers (optional)
ssh_cmd() {
  # Usage: ssh_cmd user@host "command"
  # shellcheck disable=SC2086
  eval ssh $SSH_OPTS "$@"
}

scp_cmd() {
  # Usage: scp_cmd source user@host:dest
  # shellcheck disable=SC2086
  eval scp $SSH_OPTS "$@"
}

rsync_cmd() {
  # Usage: rsync_cmd local/ user@host:remote/
  # shellcheck disable=SC2086
  eval rsync -avz -e "ssh $SSH_OPTS" "$@"
}



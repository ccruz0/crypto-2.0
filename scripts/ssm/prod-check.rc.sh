# Shell snippet: define prod-check → SSM remote /home/ubuntu/run_atp_checks.sh
#
# Bash (recommended):
#   echo 'source /path/to/crypto-2.0/scripts/ssm/prod-check.rc.sh' >> ~/.bashrc
#
# zsh: either set CRYPTO2_ROOT first, or use bash to resolve paths:
#   export CRYPTO2_ROOT="$HOME/path/to/crypto-2.0"
#   source "$CRYPTO2_ROOT/scripts/ssm/prod-check.rc.sh"
#
# Optional: AWS_PROD_INSTANCE_ID, AWS_REGION

if [[ -n "${CRYPTO2_ROOT:-}" ]]; then
  _ATP_SS_ROOT="$CRYPTO2_ROOT"
elif [[ -n "${BASH_SOURCE[0]:-}" ]]; then
  _ATP_SS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
else
  _ATP_SS_ROOT=""
  echo "prod-check.rc.sh: export CRYPTO2_ROOT=/path/to/crypto-2.0 then source again (or use bash)." >&2
fi

prod-check() {
  [[ -n "${_ATP_SS_ROOT:-}" ]] || {
    echo "prod-check: CRYPTO2_ROOT / repo root unknown" >&2
    return 1
  }
  bash "$_ATP_SS_ROOT/scripts/ssm/prod-check.sh"
}

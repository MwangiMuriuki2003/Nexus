#!/usr/bin/env bash
#
# One-command launcher for Nexus.
#
#   ./run.sh                 # desktop UI
#   ./run.sh --headless      # web UI on http://localhost:8080
#   ./run.sh setup           # first-time setup / model check
#   ./run.sh --headless --port 9000 --host 0.0.0.0
#
# It activates the conda env, works around this machine's pip config, installs the
# package on first use, and then hands over to `python -m Nexus`. Everything after
# the script name is passed through, so all CLI flags still work.
#
# Environment overrides:
#   NEXUS_CONDA_ENV   conda env name (default: ml-lab)
#   CONDA_BASE        conda installation root, if it is not found automatically

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

CONDA_ENV="${NEXUS_CONDA_ENV:-ml-lab}"

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

find_conda_base() {
    if [[ -n "${CONDA_BASE:-}" && -f "$CONDA_BASE/etc/profile.d/conda.sh" ]]; then
        printf '%s\n' "$CONDA_BASE"
        return 0
    fi
    if [[ -n "${CONDA_EXE:-}" ]]; then
        local base
        base="$(dirname -- "$(dirname -- "$CONDA_EXE")")"
        [[ -f "$base/etc/profile.d/conda.sh" ]] && { printf '%s\n' "$base"; return 0; }
    fi
    local candidate
    for candidate in "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/miniconda3" \
                     "$HOME/anaconda3" /opt/conda /usr/local/conda; do
        if [[ -f "$candidate/etc/profile.d/conda.sh" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# --- 1. conda environment -----------------------------------------------------

if [[ "${CONDA_DEFAULT_ENV:-}" != "$CONDA_ENV" ]]; then
    conda_base="$(find_conda_base)" || die "could not find conda (set CONDA_BASE=/path/to/miniforge3)"
    # shellcheck disable=SC1091
    source "$conda_base/etc/profile.d/conda.sh"
    conda activate "$CONDA_ENV" || die "conda env '$CONDA_ENV' not found (create it, or set NEXUS_CONDA_ENV)"
    echo "using conda env: $CONDA_ENV"
fi

# --- 2. pip config workaround -------------------------------------------------

# ~/.config/pip/pip.conf sets require-virtualenv=true, which makes pip refuse to
# run even inside conda. The env var overrides the config file.
export PIP_REQUIRE_VIRTUALENV=0

# --- 3. install on first use --------------------------------------------------

if ! (cd /tmp && python -c "import Nexus" >/dev/null 2>&1); then
    echo "Nexus is not installed in '$CONDA_ENV' — installing (editable)..."
    python -m pip install -e "$REPO_ROOT"
fi

# Data directories must exist before the stores open.
python -c "from Nexus.config import ensure_dirs; ensure_dirs()"

# --- 4. launch ----------------------------------------------------------------

exec python -m Nexus "$@"

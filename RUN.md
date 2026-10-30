# Running Nexus

Local-first desktop assistant: PyQt6 UI → intent router → local GGUF model (llama.cpp) →
memory (SQLite + ChromaDB) → skill registry/sandbox → optional Nebius cloud burst.

Everything below is run **from the repository root** (the directory that contains `Nexus/`,
`pyproject.toml` and this file), inside the conda environment `ml-lab`.

```
<repo root>/
├── Nexus/            # the Python package (Nexus/__main__.py is the entry point)
│   └── web/          # headless HTTP server + single-page UI
├── tests/            # pytest suite
├── run.sh            # one-command launcher (activate, install, start)
├── pyproject.toml    # packaging: console script `nexus`, pytest config
└── RUN.md            # this file
```

## Fast path

`run.sh` does steps 1, 2 and 4 for you and passes every argument through to
`python -m Nexus`:

```bash
./run.sh                    # desktop UI
./run.sh --headless         # web UI on http://localhost:8080
./run.sh setup              # first-time setup / model check
./run.sh --headless --port 9000 --host 0.0.0.0
./run.sh --help             # all CLI flags
```

It activates `ml-lab` (override with `NEXUS_CONDA_ENV`), exports
`PIP_REQUIRE_VIRTUALENV=0`, installs the package the first time it is missing, creates
`~/.nexus`, then execs `python -m Nexus`. The rest of this file is the same thing by hand,
which is what you want when debugging.

---

## 1. Activate the environment

```bash
conda activate ml-lab
python --version    # must be 3.11+
```

`pyproject.toml` requires Python >= 3.11. Install into one env only — do not mix `base`
with `ml-lab`.

---

## 2. Install

> **Gotcha on this machine:** the user-level pip config (`~/.config/pip/pip.conf`) sets
> `require-virtualenv = true`. Inside a conda env pip still refuses with
> `ERROR: Could not find an activated virtualenv (required).`
> Prefix pip calls with `PIP_REQUIRE_VIRTUALENV=0` (the env var overrides the config).

```bash
PIP_REQUIRE_VIRTUALENV=0 python -m pip install -e .
```

That installs the `Nexus` package in editable mode, every dependency from `pyproject.toml`,
and the `nexus` console script (`~/.conda/envs/ml-lab/bin/nexus`). Verify:

```bash
which nexus                                   # .../envs/ml-lab/bin/nexus
cd /tmp && python -c "import Nexus; print(Nexus.__file__)"   # works outside the repo
```

Because the install is editable, edits under `Nexus/` take effect immediately — no reinstall.
See §10 for the files this step generates and which of them are safe to delete.

### One dependency needs help: `llama-cpp-python`

PyPI ships only a source distribution, so a plain `pip install` compiles llama.cpp
(several minutes, needs `gcc`/`g++`/`cmake`/`make`). The prebuilt CPU wheel is much faster:

```bash
PIP_REQUIRE_VIRTUALENV=0 python -m pip install --only-binary=:all: llama-cpp-python \
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

Use `--extra-index-url .../whl/cu124` (matching your CUDA) for a GPU build, or
`pip install "nexus-desktop[cuda]"` for the project's CUDA extra.

---

## 3. Get the local model

`Nexus/config.py` expects this exact file:

```
~/.nexus/models/Llama-3.1-Nemotron-Nano-4B-v1-Q4_K_M.gguf
```

Download it from `nvidia/Llama-3.1-Nemotron-Nano-4B-v1` (a ~2.5 GB GGUF):

```bash
PIP_REQUIRE_VIRTUALENV=0 python -m pip install -U huggingface_hub
mkdir -p ~/.nexus/models
huggingface-cli download nvidia/Llama-3.1-Nemotron-Nano-4B-v1 \
  Llama-3.1-Nemotron-Nano-4B-v1-Q4_K_M.gguf --local-dir ~/.nexus/models
```

`LocalLLM` defaults to `n_gpu_layers=-1` (offload everything). On a CPU-only box that is
harmless but slow; `LocalLLM(path, n_ctx=4096, n_gpu_layers=0)` forces CPU.

The app starts **without** the model: the window opens, the status bar says the model is
missing, and sending a message explains what to download. Nothing else is blocked.

---

## 4. First-run setup

```bash
python -m Nexus setup
```

Creates `~/.nexus/{models,skills,sandbox}`, reports the data directory, and tells you whether
the GGUF is present (with the exact download command if it is not).

Settings are overridable with `NEXUS_*` env vars (the pydantic prefix), e.g.
`NEXUS_DATA_DIR=/tmp/nexus-data`. Cloud bursts need an API key — either `NEXUS_NEBIUS_API_KEY`
or one you paste yourself in **Edit → Settings** (stored in the OS keyring, or in
`~/.nexus/cloud_api_key` with `0600` when no keyring exists); with neither, the privacy gate
stays local-only instead of failing.

---

## 5. Launch

### Desktop app

```bash
python -m Nexus        # or: nexus
```

Needs an X/Wayland session. Over SSH use `ssh -X`, or a virtual screen:

```bash
Xvfb :99 -screen 0 1280x800x24 &
DISPLAY=:99 python -m Nexus
```

The **Edit → Settings** menu (Ctrl+,) is where you bring your own API key: provider, base URL,
model and the key itself. Saving applies immediately — the running engine picks the new key up
without a restart — and **Remove stored key** puts the app back into local-only mode.

The **View → Privacy Dashboard** menu (Ctrl+Shift+P) opens the audit log, local-vs-cloud
counters and memory statistics.

### Headless (web UI)

For a machine with no display — a server, a container, an SSH session:

```bash
./run.sh --headless                  # or: python -m Nexus --headless
# Nexus headless server: http://localhost:8080/
```

Open that URL in a browser. It is the same engine as the desktop app, so intent routing,
memory, skills and the privacy gate behave identically; only the front end differs.

| Endpoint | Purpose |
|---|---|
| `GET /` | single-page chat UI (no build step, no external assets) |
| `GET /favicon.png` | project icon (also at `/favicon.ico`; type sniffed from magic bytes) |
| `GET /api/status` | model present/loaded, data dir, local-only flag, skill and episode counts |
| `POST /api/chat` | `{"message": "..."}` → `{"response", "intent", "cloud_approved"}` |
| `GET /api/skills` | registered skills |
| `GET /api/audit?limit=N` | audit log entries (max 500) |
| `GET /api/settings` | provider, base URL, model, key status (`key_masked` only — never the secret) |
| `POST /api/settings` | `{provider?, base_url?, model?, api_key?, remove_key?}` → current settings |

```bash
curl -s http://localhost:8080/api/status | python -m json.tool
curl -s -X POST http://localhost:8080/api/chat \
  -H 'Content-Type: application/json' -d '{"message": "hello"}'
```

Behaviour worth knowing:

- **Binds `127.0.0.1` by default.** Pass `--host 0.0.0.0` to accept connections from outside
  (needed in Docker); anyone who can reach the port can talk to your assistant, so keep it
  on localhost unless you mean it.
- **Starts without the model.** `/` and `/api/status` work immediately; `POST /api/chat`
  answers `503` with the exact download command until the GGUF from §3 exists. The engine
  is built on the first chat request, so startup is instant.
- **One request at a time.** The server is single-threaded on purpose: it keeps the SQLite
  memory stores and the llama.cpp context on one thread. Two browser tabs take turns; a
  long generation blocks other requests until it finishes.
- Cloud bursts still go through the privacy gate, which denies without an approval UI, so
  `!ultra` messages in the web UI run locally and are logged as denials.

### Library use

```python
from Nexus.core.engine import NexusEngine
from Nexus.config import settings

engine = NexusEngine(settings=settings)
result = engine.process_message("what did i copy yesterday")
print(result["intent"].name, result["response"])
```

`NexusEngine(settings, privacy_gate=None, llm=None)` also accepts your own
privacy gate or model object, which is how the tests run the pipeline without a GGUF.

---

## 6. Tests

```bash
python -m pytest tests/ -q
```

Expected: **30 passed, 1 skipped**. `pyproject.toml` sets `testpaths = ["tests"]` and
`pythonpath = ["."]`, so no path juggling is needed.

The skipped test is the full-pipeline chat (`tests/test_nexus.py::test_engine_end_to_end`):
it is gated on the GGUF model existing in `~/.nexus/models/`. Download the model (§3) and it
runs too.

What the suite covers:

| File | Coverage |
|---|---|
| `tests/test_core.py` | intent routing, privacy gate denial + audit write, AST policy allow/deny lists |
| `tests/test_memory.py` | episodic SQLite search + limits, ChromaDB add/query/batch, embedder vectors and similarity |
| `tests/test_skills.py` | registry CRUD + duplicate rejection, executor construction, prompt template |
| `tests/test_nexus.py` | memory round-trip, skill register → sandboxed execution, rejected imports, engine routing with a stub LLM (no cloud call), model-gated end-to-end chat |
| `tests/test_web.py` | headless server: page, status, chat via a stub and via a real engine, 400/404/503 handling, skills and audit endpoints |

First run loads `all-MiniLM-L6-v2` from the local Hugging Face cache; if it is not cached yet,
that download happens once and is slow but is the only network use.

---

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ERROR: Could not find an activated virtualenv (required).` | user pip config sets `require-virtualenv`; prefix `PIP_REQUIRE_VIRTUALENV=0` |
| `No module named 'Nexus'` | activate `ml-lab`, or reinstall with `pip install -e .` |
| `ModuleNotFoundError: llama_cpp` | install the wheel (§2) |
| `llama_cpp` build fails with `CMake Error` / OOM | use the prebuilt wheel index, or `CMAKE_ARGS="-DGGML_NATIVE=OFF"` with `--no-cache-dir` |
| `RuntimeError: Failed to load model` | GGUF missing at `~/.nexus/models/…Q4_K_M.gguf`; redo §3 |
| Status bar: "No local model at …" | same as above — the UI stays usable |
| `qt.qpa.plugin: could not load the Qt platform plugin "xcb"` | no display / missing `libxcb`; use `Xvfb` or a desktop session |
| Slow first message | the GGUF is being memory-mapped and the first tokens are generated |
| Slow/dropped downloads from PyPI or Hugging Face | the network here is very slow (~20 KB/s observed); let installs run in the background |

---

## 8. Quick reference

```bash
conda activate ml-lab
export PIP_REQUIRE_VIRTUALENV=0

python -m pip install -e .                                  # package + deps + `nexus` script
python -m pip install --only-binary=:all: llama-cpp-python \
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu   # if needed

huggingface-cli download nvidia/Llama-3.1-Nemotron-Nano-4B-v1 \
  Llama-3.1-Nemotron-Nano-4B-v1-Q4_K_M.gguf --local-dir ~/.nexus/models

python -m Nexus setup           # create ~/.nexus, check model
python -m Nexus                # desktop UI
python -m Nexus --headless     # web UI on http://localhost:8080
python -m pytest tests/ -q

./run.sh                       # same thing, one command
./run.sh --headless --port 9000
```

---

## 9. Status on this machine

Verified after the fixes (`ml-lab`, Python 3.11.15):

| Step | Result |
|---|---|
| `pip install -e .` | installs `nexus-desktop` 0.1.0 editable + all deps + `nexus` script |
| `import Nexus` from `/tmp` | resolves to the repo source tree |
| `nexus --help` | prints usage (`setup`, `--headless`, `--port`, `--host`) |
| `./run.sh --help` | activates `ml-lab`, then prints the same usage |
| `./run.sh --headless --port 8099` | serves `/` (HTML), `/api/status`, `/api/chat`, `/api/skills`, `/api/audit`, `/api/settings`; chat returns 503 with the download command while the GGUF is absent |
| `python -m Nexus setup` | creates `~/.nexus/…`, reports the missing GGUF and how to fetch it |
| Headless GUI smoke (`QT_QPA_PLATFORM=offscreen`) | window builds, status reports the missing model, Privacy Dashboard opens and reads the audit DB |
| `LocalLLM` against a cached GGUF | loads and returns a chat completion through llama.cpp |
| `pytest tests/` | 30 passed, 1 skipped (needs the GGUF) |
| Nebius cloud burst | not exercised — no API key; the gate denies and logs locally by default |
| Docker | no Dockerfile in the repo; a container would run `python -m Nexus --headless --host 0.0.0.0` (README updated to match) |

---

## 10. Generated files: what you can delete

None of these are source. They appear as a side effect of installing, running or testing, and
every one of them is rebuilt automatically.

| Path | Created by | Safe to delete? |
|---|---|---|
| `nexus_desktop.egg-info/` | setuptools during `pip install -e .` | **Yes.** Regenerated by the next install. |
| `__pycache__/` (one per package) | the interpreter | **Yes.** Always rebuilt; delete freely. |
| `.pytest_cache/` | `pytest` | **Yes.** Only stores last-run state. |
| `~/.nexus/` | `python -m Nexus setup` + first use | **No — this is your data.** |

**`nexus_desktop.egg-info/`** is distribution metadata, named after `name = "nexus-desktop"` in
`pyproject.toml`. It holds `PKG-INFO` (rendered package metadata), `requires.txt` (resolved
dependencies), `entry_points.txt` (the `nexus = Nexus.__main__:main` console script),
`top_level.txt` (just `Nexus` — the file that proves the `include = ["Nexus*"]` setting found
the package), and `SOURCES.txt` (file manifest). Nothing imports from it.

Deleting it does **not** immediately remove the `nexus` command, because the running install
lives in site-packages, not here:

```
<env>/lib/python3.11/site-packages/
├── __editable__.nexus_desktop-0.1.0.pth              # puts the repo on sys.path
├── __editable___nexus_desktop_0_1_0_finder.py        # maps `Nexus` to this source tree
└── nexus_desktop-0.1.0.dist-info/                    # installed metadata
```

Those are removed by `pip uninstall nexus-desktop`, not by deleting the egg-info. So the safe
sequence for a clean rebuild is:

```bash
rm -rf nexus_desktop.egg-info .pytest_cache
find . -name __pycache__ -type d -exec rm -rf {} +
PIP_REQUIRE_VIRTUALENV=0 python -m pip install -e .   # regenerates egg-info
```

**`~/.nexus/` is different — do not delete it to "clean up".** It is the application's data
directory, not build output: `episodic.db` (chat history), `chroma/` (semantic vectors),
`audit.db` (privacy audit log), `skills/skills.db` (registered skills, created the first time a
skill is registered) and `models/` (the GGUF from §3). `sandbox/` is scratch space for skill
execution and can be emptied safely. Removing the directory as a whole wipes your memory,
skills and audit trail, and the GGUF would need re-downloading. To relocate it instead, set
`NEXUS_DATA_DIR=/some/path`.

`.gitignore` in this repo is currently empty and the directory is not a git repository yet, so
before the first commit add at least:

```gitignore
*.egg-info/
__pycache__/
*.py[cod]
.pytest_cache/
build/
dist/
```

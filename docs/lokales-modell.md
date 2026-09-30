# Local model: Hermes without the cloud, on your own GPU (optional)

As of 2026-09-27. How Hermes on hermes-os runs with a model that computes on
the machine itself, what the image ships for it and what is only downloaded
on request, why it is built this way, and where its limits are.

## Decision: optional, Ollama not in the image

The local model is an option, not a component. Since 2026-09-27 Ollama itself
is no longer in the image; if you want it, `ujust hermes-lokal-ein` or the
card in the setup assistant downloads it into your home directory. Reasons:

- **Small models add little.** What fits on a 12 GB card falls clearly
  behind the cloud models at tool calls (in VM 112, `qwen3.5:4b` missed the
  meta tool `tool_call` and fell back to web search). That does not justify
  weighing down every image with it.
- **About 0.9 GB less in both images** (`/usr/lib/ollama`, 0.85 GB of it
  CUDA 13), and no image bump for an Ollama bump.
- **The CUDA runtime is no longer in the image.** The Ollama archive
  contains cuBLAS and cudart; while it was in the image, hermes-os
  redistributed them. Now the archive comes to the machine on request,
  directly from Ollama's releases. Whether this fully settles NVIDIA's
  redistribution terms has not been checked; the image itself no longer
  contains any of it.

What stays in the image: the user service `ollama.service` (it points to the
program in the home directory and quietly stays off without it), the helper
`hermes-os-lokal`, the module `local_model.py`, the recipes, the card in the
setup assistant, and `zstd` for unpacking. No other part of hermes-os
depends on the local model.

**Downloaded on request, pinned as it used to be in the build.**
`local_model.install_ollama` downloads `ollama-linux-amd64.tar.zst` at
version `OLLAMA_PIN` from `github.com/ollama/ollama/releases`, compares its
SHA256 with `OLLAMA_SHA256` (taken from the release's `sha256sum.txt`),
unpacks it without `cuda_v12` into `~/.local/share/hermes-os/ollama/{bin,lib}`
and writes the stamp `.hermes-os-release` (version, checksum, backends).
Before that it checks disk space: archive (1.3 GB) and result (0.9 GB) sit
side by side while unpacking, plus 1 GB of headroom. It replaces an existing
Ollama only after the checksum, the unpacking and a test run
(`ollama --version`); if a step fails, the old state stays.

## Why Ollama, and why as a user service

**Ollama instead of llama-server.** Both provide an OpenAI-compatible
endpoint with tool calls, which Hermes addresses as provider `custom`. The
difference is everything around it: Ollama pulls models from its library
with progress (`/api/pull`), manages them (`/api/tags`, `/api/show` with
capabilities such as `tools` and context length), picks the compute backend
itself at startup (CUDA, Vulkan, CPU) and keeps a model in memory after use.
The setup assistant and the ujust recipes need exactly that. llama-server
(ggml-org/llama.cpp, release b11205) now handles tool calls without an extra
flag (`--jinja` is the default) and fetches GGUF files from Hugging Face via
`-hf`, but it has no pull with progress, no model management and no automatic
backend selection; the CUDA builds exist only for Ubuntu, and whether they
run on Fedora is untested. Ollama bundles llama.cpp anyway
(`lib/ollama/llama-server` is included). For llama-server Hermes knows the
slug `llamacpp`, but that refers to Hermes' own runtime and ignores
`model.base_url`; an external llama-server would also be `custom`. That
remains open as a way out, but needs no code.

**The native archive instead of a Podman Quadlet.** The release tarball
`ollama-linux-amd64.tar.zst` (v0.34.4 from 2026-09-23, 1.3 GB, 2.2 GB
unpacked, layout checked) contains `bin/ollama` and `lib/ollama` with CPU
backends per processor family, CUDA 12 (1.3 GB), CUDA 13 (0.85 GB) and
Vulkan (43 MB). Ollama ships cuBLAS and cudart itself; from the host it only
needs `libcuda.so.1` from the driver. Reasons against the container:

- A Quadlet would have to pull `docker.io/ollama/ollama` (3.75 GB
  compressed) into the home directory, with `latest` or with a pin that
  nobody updates along with the image. The archive is smaller and pinned in
  `local_model.py`: one version, one bump, verified with SHA256.
- GPU access in a container needs CDI. `aurora-dx-nvidia-open` brings
  `nvidia-container-toolkit` and `nvidia-cdi-refresh.service` (the file sits
  at `/var/run/cdi/nvidia.yaml`), the AMD/Intel variant none of it; the
  Quadlet would differ per variant. Universal Blue had `ujust ollama` as a
  Quadlet and removed it again on 2024-11-21 (Bluefin commit `c271947`);
  today Aurora recommends ramalama via Homebrew.
- The agent on the host does not see the container: `ollama ps`, logs and
  models would sit behind `podman exec`.

**One archive for both variants.** Nothing asks about the GPU when
downloading. At startup Ollama probes every backend directory next to the
program (`~/.local/share/hermes-os/ollama/lib/ollama`): CUDA via the NVIDIA
driver (present only in the NVIDIA image), Vulkan via Mesa (AMD, Intel) or,
as a fallback, via the NVIDIA driver, otherwise the CPU, with the log line
`inference compute id=cpu`. So the AMD/Intel variant computes on an AMD or
Intel GPU via Vulkan, and on the CPU when there is no GPU; the helper says
beforehand what it finds. `cuda_v12` is not unpacked: the open kernel
modules only run from Turing onwards, which CUDA 13 covers (driver 580 or
later; Aurora stable has 615.71.09). That saves 1.3 GB in the home
directory; the program is about 0.9 GB. ROCm libraries are not included
(separate tarball, 1 GB); AMD runs via Vulkan.

**User service instead of system service.** `ollama.service` lives in
`/usr/lib/systemd/user`, is off by default and listens only on
`127.0.0.1:11434`. It starts `%h/.local/share/hermes-os/ollama/bin/ollama`
and has the same file as `ConditionPathExists`: without the downloaded
program it quietly stays off instead of running into a restart loop.
Models live in `~/.local/share/ollama/models` (`OLLAMA_MODELS`), not in
`/var/lib` and not in the hidden `~/.ollama`; an image update leaves them
alone. That keeps everything inside the boundary: `systemctl --user` and the
home directory are free, the agent may switch the service without asking
(`docs/grenze.md`), and nobody needs root. Ollama's own `install.sh` would do
the opposite (system unit, user `ollama`, drivers via dnf) and is unusable
on bootc.

## What is in the image and what is downloaded

| What | Where |
|---|---|
| Pin `OLLAMA_PIN`, archive, `OLLAMA_SHA256`, download, space check, removal | `files/system/usr/share/hermes-os/local/local_model.py` |
| Ollama, backends, stamp (downloaded, not in the image) | `~/.local/share/hermes-os/ollama/bin/ollama`, `…/lib/ollama/{cuda_v13,vulkan,…}`, `…/.hermes-os-release` |
| Models (downloaded) | `~/.local/share/ollama/models` |
| User service | `files/system/usr/lib/systemd/user/ollama.service` |
| Logic: GPU, Ollama API, suggestions, config write path | `files/system/usr/share/hermes-os/local/local_model.py` |
| Helper for the recipes, the setup assistant and the agent | `files/system/usr/libexec/hermes-os-lokal` |
| Recipes | `hermes-lokal-ein`, `-aus`, `-entfernen`, `-modell`, `-status` in `hermes-os.just` |
| Card in the setup assistant | `setup/Main.qml` (page “Local model”, German UI: „Lokales Modell“), backend in `hermes-os-setup` |
| Instructions for the agent | section “Local model instead of cloud” (German: „Lokales Modell statt Cloud“) in `skills/hermes-os-system/SKILL.md` |
| `zstd` for unpacking, PyYAML for the helper | `files/scripts/20-agent-layer.sh` |
| Test | `tests/lokales-modell-check.py`, gate `80-validate.sh` section 7m, “no Ollama in the image” in `89-tests.sh` |

## How Hermes is connected

Hermes 0.21.x (tag v2026.9.24) has no Ollama slug of its own; `ollama` is an
alias for `custom`, the provider for OpenAI-compatible servers. The helper
writes the same block into `~/.hermes/config.yaml` that Hermes' wizard
generates for a custom endpoint without a key (`_persist_model`), plus three
entries that an agent with tools needs on Ollama:

```yaml
model:
  default: qwen3.5:9b
  provider: custom
  base_url: http://127.0.0.1:11434/v1
  api_mode: chat_completions
  context_length: 65536      # caps what Hermes reads from /api/show (the GGUF says 256k)
  ollama_num_ctx: 65536      # lifts it above Hermes' minimum, even if the model reports less
agent:
  reasoning_effort: none     # Hermes then sends think:false to Ollama
```

No `.env` line is created: without a key, Hermes itself sets
`no-key-required` as the bearer token, and Ollama checks none. The key for
the gateway's API server (for the panel icon) still goes into `.env`,
because after writing the config the helper calls the first-login script;
as of this version, that script also counts a provider in `config.yaml` as a
completed setup. The gateway rereads `config.yaml` at every conversation
step and rebuilds the agent as soon as the model, address or provider
changes; no restart is needed. Sessions with their own `/model` stay on
their model.

Why not Hermes' `_persist_model` through the setup assistant's bridge: the
write path also has to run from the ujust recipe with Fedora's Python and be
testable without Hermes. Instead, the contract lives in the gate: what
`hermes-os-lokal eintragen` writes, `hermes config get` reads back, and
65536 is above `MINIMUM_CONTEXT_LENGTH`. The bridge's catalogue hides
`custom` anyway (no key), so the card comes from the setup assistant itself
as soon as `/usr/libexec/hermes-os-lokal` exists.

**64k context is mandatory.** Hermes refuses to start with tools below
64,000 tokens (`agent/agent_init.py`; the message points to
`OLLAMA_CONTEXT_LENGTH` or `model.ollama_num_ctx`). Ollama gives cards
under 23 GiB only 4096 tokens, and the OpenAI-compatible endpoint does not
accept `num_ctx` per request (Hermes sends it in `extra_body.options`, and
Ollama ignores it there). That is why the unit sets
`OLLAMA_CONTEXT_LENGTH=65536` for all models, plus `OLLAMA_FLASH_ATTENTION=1`
and `OLLAMA_KV_CACHE_TYPE=q8_0` (halves the cache), `OLLAMA_KEEP_ALIVE=1h`
and `OLLAMA_NO_CLOUD=1`. To get more, override it with
`systemctl --user edit ollama.service`.

**Tool calls.** Hermes sends only `tools` to `custom` (no `tool_choice`, no
`parallel_tool_calls`, no `max_tokens`) and expects real `tool_calls` in the
response; there is no text fallback. The model must have the `tools`
capability (Ollama library, filter “tools”). The check in the helper and in
the setup assistant sends exactly such a request with one tool definition
and only writes a model into the config if it answers with a call. Thinking
mode: without a setting, Hermes sends `reasoning_effort: medium` to custom
endpoints, and Qwen3.5 would then think before every tool step;
`agent.reasoning_effort: none` becomes `think: false` (only on port 11434)
and also prevents tool calls inside the thinking block, a known Qwen3.5
problem. The helper remembers the previous value and restores it with
`aus`. Ollama's `/v1` endpoint sets `temperature 1.0` if the client sends
none; Hermes sends none. That is not ideal for tool calls and is visible in
the VM.

## Model choice for 12 GB

Recommendation based on the research of 2026-09-26 (Ollama library, Ollama's
own Hermes guide `docs/integrations/hermes.mdx`, `cmd/launch/models.go`,
Hermes' `local-ollama-setup.md`, memory calculation by architecture). The
download sizes come from search excerpts, since `ollama.com` was not
reachable from the cloud; the VRAM figures are calculated, not measured.

| Model | Size | 64k in 12 GB | Why |
|---|---|---|---|
| **`qwen3.5:9b`** (default) | 6.6 GB | yes, about 8.5 GB with q8_0 cache | Reliable tool calls (the family leads jdhodges' tool-calling test), 201 languages, 256k model context, hybrid: only 8 of 32 layers have a KV cache (32 KiB per token instead of 160 KiB for `qwen3:14b`). Ollama itself names it as a local model for Hermes. |
| `qwen3.5:4b` (8 GB, CPU) | 3.4 GB | yes, easily | Same family; for 8 GB cards and machines without a GPU. On the CPU, the first pass over the system prompt and tool schemas takes minutes. |
| `gemma4:12b` | 7.6 GB | probably | Better German in a hands-on test; tool calls still had open bugs in September 2026 (Hermes #79639 loses the history with `tools`, Ollama #18275 broken call format). Candidate for testing. |
| `granite4:tiny-h` | 4.2 GB | yes | IBM, German officially supported, Mamba hybrid without a thinking mode. Plainer. |

Ruled out: `qwen3:14b` and `qwen3:8b` (dense models; 64k context needs 5 to
10 GiB of cache, plus a 40k context limit), `gpt-oss:20b` (14 GB, thinking
cannot be switched off, mostly English), `gemma3` and `deepseek-r1:14b` (no
tools in Ollama), `mistral-small3.2`, `devstral-small-2`, `glm-4.7-flash`,
`qwen3.6:27b`, `gemma4:31b` (15 to 20 GB). There is no Hermes 4 model from
Nous in the Ollama library.

The default is chosen by `recommend()` in `local_model.py` from the card's
memory: 12 GB `qwen3.5:9b`, 8 GB `qwen3.5:4b`, no GPU `qwen3.5:4b`. In the
setup assistant and in the recipe, the user can give any other Ollama tag;
the tool-call check still applies.

## Usage

In the setup assistant (`ujust hermes-setup`, or the menu entry
“Set up Hermes”, German default: „Hermes einrichten“): choose the provider
“Local model (Ollama)” (German UI: „Lokales Modell (Ollama)“), then, on a
single page, download Ollama (first time only, with progress and space
estimate), start the service, choose and download a model (with progress;
models that do not fit on the disk are marked), check the connection and
write the config. In the terminal or through the agent:

```sh
ujust hermes-lokal-status              # GPU, Ollama, service, models, what Hermes uses
ujust hermes-lokal-ein                 # download Ollama (if needed), service on, download default, check, write config
ujust hermes-lokal-ein qwen3.5:4b      # with a model of your choice
ujust hermes-lokal-modell gemma4:12b   # download another model, check, write config
ujust hermes-lokal-aus                 # service off, previous provider back
ujust hermes-lokal-entfernen           # like aus, plus delete Ollama and all models
```

Before every model download the helper checks the space under
`~/.local/share/ollama`: known models with their size plus 1 GB of headroom,
custom tags with a floor of 2 GB and a note that the size is unknown. If
there is not enough space, it stops before downloading.

`aus` restores the model block and `agent.reasoning_effort` from before the
switch (`~/.hermes/hermes-os/local-previous-model.json`). If no provider was
set before, Hermes is left without a model, and the setup assistant or
`hermes setup` picks a new one. For the agent, switching is free (user
service, home directory, `ujust hermes-*`), but only when the user
explicitly asks for it; the skill tells it what to announce beforehand.

## Testing

Without a GPU, without Ollama, without Hermes:

```sh
tests/lokales-modell-check.py --local-dir files/system/usr/share/hermes-os/local
```

It checks GPU detection against mocks (an `nvidia-smi` in PATH that reports
an RTX 3060; one that fails; a `/dev/kfd`; nothing), the suggestions, the
config write path against a throwaway `config.yaml` made from the template
(block, rest of the file, 0600, remembering and restoring), the endpoint
check against a mock Ollama server (`/api/version`, `/api/tags`,
`/api/show`, `/api/pull` as a stream, `/v1/models`, `/v1/chat/completions`
with and without a tool call) and the download against a mock release
archive via `file://` (wrong checksum, correct one without `cuda_v12`, too
little space, second call, removal; needs `tar` and `zstd`), plus the helper
with a `systemctl` that only records its calls. No step goes to the
internet. `make lint` and the gate (`80-validate.sh` 7m) run it; the gate
also checks that there is no Ollama in the image, and checks the unit, the
recipes and the contract with Hermes.

Only test VM 112 (RTX 3060 via passthrough, `docs/testumgebung.md`) can check
what the cloud cannot. Passed on 2026-09-27 (still with Ollama in the
image): `inference compute … library=CUDA`, `qwen3.5:4b` at 100% GPU with
context 65536, `os_services` through the local model, images in the chat,
`hermes-lokal-aus` returning to the cloud provider. The default
`qwen3.5:9b` did not fit on the VM's 31 GB disk (6.1 GB free); hence the
space check.

```sh
ujust hermes-lokal-ein                              # download Ollama, service, 6.6 GB download, check, write config
journalctl --user -u ollama.service -n 40           # "inference compute" must name CUDA
ollama ps                                           # 100% GPU, context 65536, size in VRAM
nvidia-smi --query-gpu=memory.used --format=csv     # headroom next to Plasma (about 0.5 to 1 GB)
hermes                                              # chat: "Which services have failed?" must call os_services
ujust hermes-lokal-aus                              # provider back
ujust hermes-lokal-entfernen                        # program and models gone, space back
```

If `ollama ps` shows less than 100% GPU, the context is too large for the
card: keep `OLLAMA_CONTEXT_LENGTH=65536` and use `qwen3.5:4b` instead of
lowering the context (Hermes will not start then).

## Limits and pitfalls

- **Ollama reports Vulkan for NVIDIA too.** If it finds CUDA, CUDA wins;
  without `libcuda.so.1` (AMD/Intel image on NVIDIA hardware with Nouveau)
  it runs via Vulkan and is slower. `journalctl --user -u ollama.service`
  shows at startup which backend it picks.
- **Without a GPU it is slow.** A 4B model on the CPU answers, but the first
  step with tool schemas takes minutes. The helper says so beforehand;
  `HERMES_API_TIMEOUT` in `.env` extends Hermes' patience.
- **`hermes doctor`** wrongly reports “No API key found in .env” for
  `custom` without a key. The endpoint does not need one.
- **The model list in the setup assistant** comes from
  `local_model.RECOMMENDED`; if you enter a tag that is not on it, you get no
  memory warning, only the tool check and the space floor.
- **Disk space:** Ollama itself needs about 0.9 GB, and
  `~/.local/share/ollama` grows by 3 to 8 GB per model. `ollama rm <tag>`
  removes a model; the recipe `aus` deletes nothing, `entfernen` deletes
  everything.
- **Moving from an image with Ollama in it:** the old `/usr/bin/ollama`
  disappears with the image update, while the models under
  `~/.local/share/ollama` stay. `ollama.service` stays off until
  `ujust hermes-lokal-ein` has downloaded the program into the home
  directory; after that it finds the models again.
- **Bump:** `OLLAMA_PIN` and `OLLAMA_SHA256` in `local_model.py` (value from
  the release's `sha256sum.txt`), then the steps above in VM 112. A new
  tarball may rename backend directories; the stamp
  `~/.local/share/hermes-os/ollama/.hermes-os-release` shows which backends
  came with it.

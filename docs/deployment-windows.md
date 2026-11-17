# Windows lab PC deployment (M4)

Status: **checklist only.** Nothing here has run on the lab PC yet; it is executed later with the owner present.
Plan of record: blueprint §7 (procedure), §4.4 (residual risks), §5.4 (harness wiring), §9.5 (WP4.2), §10 (owner
decisions D1–D3). After this document, bring the instrument up with [hardware-bringup.md](hardware-bringup.md).

**The idea in one paragraph.** Everything lives in one folder, the `git clone` of this repository: the Python
environment (`.venv\`), your local configuration (`config\local\`), the run archive and state (`data\`) and the
agent's scratch (`work\`). Nothing needs administrator rights except the VISA driver for the GPIB adapter. Updating
means `git pull`. The coding agent (Codex, optionally Claude Code) reaches the B1500A only through the b1500 server;
a measurement that needs your consent stops and asks you in the harness's own approval prompt.

## Facts to collect first

Fill in the last column before step 1. Where a fact is unknown, the default applies.

| Fact | Why it matters | Where to find it | Default if unknown | Value |
|---|---|---|---|---|
| GPIB adapter model | Decides the VISA stack; USB adapters may need an even GPIB address (PG PDF 23) | Label on the adapter; Windows Device Manager | Keysight 82357B (USB/GPIB) | |
| VISA vendor, and whether a second VISA is installed | PyVISA loads the system default VISA; two stacks can conflict | Windows "Installed apps": Keysight IO Libraries Suite, NI-VISA | The stack that belongs to the adapter, only one; `visa.library: ""` | |
| B1500A GPIB address | `visa.resource` in `config\local\settings.yaml` | B1500A FlexGUI window or its Connection Expert (PG PDF 23) | 17, i.e. `GPIB0::17::INSTR` | |
| Internet access (PyPI, harness login and model use) | `uv sync`, `uv python install` and both harnesses need it | Open pypi.org in a browser; ask lab IT about a proxy | Online. The harnesses always need the internet; for an offline dependency install see step 3 | |
| Offline wheelhouse needed | Only if PyPI is blocked but the harness can still reach its service | Lab IT | Not needed | |
| EasyEXPERT coexistence | EasyEXPERT must be ended while b1500 controls the B1500A (PG PDF 23) | Ask the people who use EasyEXPERT on the instrument; is EasyEXPERT set to auto-start? | Never at the same time: EasyEXPERT ended (File > Exit, Start EasyEXPERT button left on screen) whenever b1500 works | |
| Harness choice and versions | Behaviour of approvals and rules depends on the version | `codex --version`, `claude --version`, `uv --version`, `git --version` | Codex only; the versions of the latest M3 report in `docs/acceptance/` or newer; Claude Code at least 2.1.295 | |
| Backup of `data\runs\` | Runs exist only in the clone | Ask the owner: target folder and rhythm | No automatic backup; copy `data\runs\` and `config\local\` at the end of each measurement day (step 9) | |
| Clone folder | Long or non-ASCII paths cause Windows path problems; `doctor` warns above 80 characters | Choose | `C:\b1500\test_agent` | |
| Windows account and admin rights | The VISA driver installer needs admin rights once | Lab IT | Lab IT installs the VISA stack; everything else installs per user without admin rights | |
| Power-line frequency | Run-time estimates assume 50 Hz | EasyEXPERT Configuration window, Main Frame tab | 50 Hz | |
| Git remote and branch | What `git clone` and `git pull` fetch | The developer | The developer's remote, branch `main` | |

## Procedure

Run every command in **PowerShell**, in the clone folder from step 2 on. Native Windows only, not WSL (a Linux
process cannot load the vendor VISA DLL or see the USB/GPIB adapter).

### Step 1 — Install the prerequisites (once)

1. **Git for Windows** (a per-user install is fine). Claude Code also needs it for its Bash tool.
2. **uv**, without admin rights, with either `winget install --id=astral-sh.uv -e` or
   `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`. Open a new PowerShell
   window and check `uv --version`.
3. **Python 3.12 x64** through uv: `uv python install 3.12` (kept in uv's own folder, no admin rights).
4. **VISA stack and GPIB adapter driver — one vendor only:** Keysight IO Libraries Suite with a Keysight 82357B, or
   NI-VISA with NI-488.2 and an NI GPIB-USB-HS. This is the only step that needs admin rights (usually lab IT). Check:
   the vendor tool (Keysight Connection Expert or NI MAX) lists the instrument at `GPIB0::17::INSTR` once
   EasyEXPERT is ended on the B1500A ([hardware-bringup.md](hardware-bringup.md), Stage 0).
5. **Coding harness:** the Codex CLI for Windows (native, PowerShell, sign in once). Optional: Claude Code with
   `irm https://claude.ai/install.ps1 | iex` (no admin rights) and sign in.
6. **UTF-8 mode for Python:** `setx PYTHONUTF8 1` (user environment; takes effect in new windows). The generated
   harness configs set it for the server anyway; `doctor` warns when it is missing.

pip instead of uv is possible for the command line only: on a PC with uv, export the locked versions with
`uv export --frozen --no-dev --no-hashes --output-file requirements.txt`; on the lab PC (Python 3.12 x64 from
python.org, per-user install) create `.venv` with `python -m venv .venv` and install with
`.venv\Scripts\python -m pip install -r requirements.txt` and `.venv\Scripts\python -m pip install --no-deps -e .`.
The generated harness configs and the Claude Code hook start `uv`, so the agents need uv.

### Step 2 — Get the code

```powershell
git clone --branch main REMOTE_URL C:\b1500\test_agent
cd C:\b1500\test_agent
git status
```

`REMOTE_URL` and the branch come from the facts table. Later updates use `git pull` (step 9). Line endings are
handled by the committed `.gitattributes`.

### Step 3 — Install the dependencies

```powershell
uv sync --frozen
uv run b1500 --help
```

`uv sync --frozen` creates `.venv\` inside the clone exactly as `uv.lock` says.

**Offline PC** (only if the facts say so; not tested yet, `TODO(verify)`). On an online Windows x64 PC with the same
Python minor version, in a clone of the same commit:

```powershell
uv export --frozen --no-hashes --output-file requirements.txt
python -m pip download -r requirements.txt -d wheelhouse
```

Copy `wheelhouse\` to the lab PC, then run `uv sync --frozen --offline --find-links wheelhouse` there. If uv
refuses, use the pip route of step 1 with `--no-index --find-links wheelhouse` added to the `pip install` commands.

### Step 4 — Create the local configuration

```powershell
New-Item -ItemType Directory -Force config\local\pinmaps, config\local\duts
Copy-Item config\settings.example.yaml config\local\settings.yaml
Copy-Item config\station.example.yaml config\local\station.yaml
Copy-Item config\policy.example.yaml config\local\policy.yaml
uv run b1500 config check
```

Edit the copies (you, not the agent; the agent is never allowed to edit `config\local\`):

- `settings.yaml`: `backend: visa`; `visa.resource` from the facts table; `visa.library` only when two VISA stacks
  are installed; keep the `\n` terminations (checked at bring-up L0, ATV-2).
- `station.yaml`: `name`; `modules` = the EasyEXPERT module list (slot, model, type, channels, alias);
  `interlock.available` stays `null` until the bring-up Stage 0 test; record cables in `topology`.
- `policy.yaml`: keep the defaults. You may only tighten them; anything above 42 V or 100 mA makes the configuration
  invalid.
- `pinmaps\` and `duts\`: written stage by stage during the bring-up, starting with `certainty: unverified`. Example
  pin maps and DUT profiles are never used with `backend: visa`. Never name a local file `*.example.yaml`.

`uv run b1500 config check` must say `config: valid` with backend `visa` because of `config\local\settings.yaml`.

### Step 5 — Check the installation and probe the instrument

Prerequisite: bring-up Stage 0 is signed off and EasyEXPERT is ended on the B1500A.

```powershell
uv run b1500 doctor
uv run b1500 doctor --probe
```

- `doctor`: no FAIL line. Until step 6, "harness files" is a WARN; `LongPathsEnabled` may WARN (keep the clone path
  short instead of changing the registry).
- `doctor --probe` is not implemented on visa in v1 (it says so and exits with code 2); until it is, use
  `uv run b1500 status` as described in [hardware-bringup.md](hardware-bringup.md), L0. The L0 stage of the
  bring-up is the full version of this step.

### Step 6 — Wire the harness

```powershell
uv run b1500 harness init --codex
uv run b1500 harness init --codex --check
uv run b1500 dev mcp-smoke --config .codex/config.toml --expect-backend visa
uv run b1500 doctor
```

For Claude Code also run `uv run b1500 harness init --claude` and
`uv run b1500 dev mcp-smoke --config .mcp.json --expect-backend visa`. `harness init` writes the machine-specific
`.codex\config.toml` / `.mcp.json` with this clone's absolute path; `mcp-smoke` starts the server exactly as the
harness will, expects the ten tools and calls `station_status` without instrument I/O. `doctor` now shows
"harness files" PASS with `run_confirmed_plan` = `prompt` (Codex) / `ask` (Claude Code).

### Step 7 — Launch Codex and check it

```powershell
codex
```

Start it from the clone root, with no extra flags.

1. **Trust the project** when Codex asks. Without trust Codex ignores the project's `.codex\config.toml` and its
   rules. Check: `codex mcp list` in the clone lists `b1500` as enabled.
2. **Sandbox check (required).** Codex must run with the default `workspace-write` sandbox and must ask before
   approval-gated tools. Run `codex doctor --summary` in the clone: the `sandbox` row must read `restricted fs …` and
   the approval must not be `Never`. Codex 0.167.1 on macOS prints
   `restricted fs + restricted network · approval OnRequest` for workspace-write and
   `unrestricted fs + enabled network · approval Never` for full access; the Windows wording may differ slightly.
   If not, open `%USERPROFILE%\.codex\config.toml`, remove
   `sandbox_mode = "danger-full-access"` and `approval_policy = "never"` (also inside any `[profiles.…]` table),
   restart Codex and check again. Why: a user config that defaults to full access makes every approval moot,
   including the `prompt` on `run_confirmed_plan` (found during M3, WP3.1).
3. **Never** start Codex with `--dangerously-bypass-approvals-and-sandbox` (`--yolo`), `--sandbox danger-full-access`,
   `--ask-for-approval never` or `--approve-for-me`, and never switch a running session to full access.
4. **ATV-4 check (server can open VISA; also the last step of bring-up L0).** Ask Codex: "Call station_status and
   report backend, identity and modules." Expected: `backend: visa`, the B1500A identity and the module table. Codex
   sandboxes the commands it runs; the MCP server is expected to run outside that sandbox, which is what lets it open
   the VISA library. Fallback if it fails while `uv run b1500 status` works with Codex closed: follow the Codex
   documentation for MCP servers that need device access and write the setting into "Recorded results" below.
5. **ATV-11 check (the approval prompt shows the summary).** Needs the DUT disconnected and the two L1 files of the
   bring-up (`open-smu3` pin map, `open-circuit` DUT profile; create them now as described there, or do this check
   when you reach L1). Ask: "Validate basic.contact_resistor with v_start=0 and v_stop=0 on pin map open-smu3 with DUT
   profile open-circuit, then run it." Expected: the agent shows the plan summary, says it needs your confirmation and
   stops. Reply "Confirmed, go ahead". Codex's approval prompt for `run_confirmed_plan` must show the `summary`
   argument; compare it, then **decline** (nothing is sent to the instrument). Fallback if the prompt hides the
   arguments: approve real runs only after comparing the summary the agent printed in the chat (the skill makes it
   print the summary verbatim; M3 scenario S4 checks that); record it.
6. Close Codex again before continuing the bring-up with the command line (one b1500 process at a time).

### Step 8 — Claude Code (optional)

1. `claude --version` is 2.1.295 or later (needed for the hook's fail-closed setting) and `uv` is on `PATH`: the
   guard hook runs through `uv`, and if it cannot start, every shell and file-edit call of Claude Code is blocked
   until it is fixed.
2. Start `claude` in the clone root and **approve the project MCP server `b1500` once** when asked. Check:
   `claude mcp list` shows `b1500` connected (before the approval it says "Pending approval").
3. Use the default permission mode (accept-edits is fine). Never use `--dangerously-skip-permissions`, never set
   `"defaultMode": "bypassPermissions"` in `%USERPROFILE%\.claude\settings.json` or `.claude\settings.local.json`.
   Claude Code has no sandbox on native Windows, so its deny rules and the hook are the second layer.
4. **ATV-8 check (hook active).** In Claude Code, `/hooks` lists the `PreToolUse` hook
   `scripts/hooks/b1500_guard.py` for Bash, PowerShell, Write, Edit, MultiEdit and NotebookEdit. Whether hooks also
   run in bypass-permissions mode is not verified; fallback: that mode is never used here (accepted residual, D3),
   and the deny rules hold in every mode.
5. **ATV-7 and ATV-11 check.** Repeat the request of step 7.5. The `run_confirmed_plan` prompt must appear in the
   default mode and show the `summary`; decline it. Fallback (ATV-7): the `requiresUserInteraction` flag (policy
   `confirmation.claude_require_user_interaction: true`, the default) forces the prompt; if no prompt appears at all,
   do not use Claude Code with the instrument and record it.

### Step 9 — Daily use and updates

- Each measurement day: the interlock test of bring-up Stage 0 (the User Guide asks for it daily, UG PDF 142),
  EasyEXPERT ended, then `uv run b1500 status` with the harness closed, or `station_status` through the agent.
- **One b1500 process at a time:** a running harness keeps the instrument's VISA session open, so close it before
  using the CLI on the instrument (details: [hardware-bringup.md](hardware-bringup.md), "One b1500 process at a
  time").
- Human-only commands, typed by you, never by the agent: `uv run b1500 run --confirm PLAN_ID` and
  `uv run b1500 fault clear --by NAME` (the latter only after a verified `uv run b1500 shutdown`).
- **Update:** close the harness, then

  ```powershell
  git pull
  uv sync --frozen
  uv run b1500 harness init --codex --check
  uv run b1500 doctor
  ```

  If the check reports drift, run `uv run b1500 harness init --codex` again (and `--claude` if used). `git pull`
  never touches `config\local\` or `data\` (both are ignored by git). After a harness upgrade repeat steps 7.2, 7.5
  and, for Claude Code, 8.4–8.5.
- **Backup** (see the facts table), for example to `D:\b1500-backup`:

  ```powershell
  robocopy data\runs D:\b1500-backup\runs /E
  robocopy config\local D:\b1500-backup\config-local /E
  ```

## Residual risks in plain words

**What the software guarantees in normal use.** A measurement that needs your consent runs only after you approve
it in the harness prompt, which shows the plan summary. The agent cannot run such a plan through the ordinary run
tool, and a blocked plan cannot run from the chat at all. Whatever is approved or configured, the library never
goes above 42 V or 100 mA, stays within each module's ratings and checks every output command against the plan.
Every run records what was approved and the fingerprints (sha256) of the configuration files it used.

**What it does not guarantee (accepted by the owner, decision D3):**

- **Approvals switched off.** If Codex runs with full access, `--yolo` or approval `never`, or Claude Code in bypass
  mode, the agent can approve its own measurements. Codex then does not ask at all; Claude Code still asks for
  `run_confirmed_plan` because the tool is flagged to always need you. Keep the default modes (steps 7 and 8).
- **The agent's own code.** An agent with a shell can write and run its own Python, even a raw PyVISA script, or
  type into a terminal it controls (it could answer the `y/N` of the human-only command itself). Such code bypasses
  every software limit; then only the open interlock (±42 V in hardware) still holds. The project rules, Codex's
  forbidden rules, Claude Code's deny rules and its hook make this unlikely, not impossible.
- **Configuration edits.** Codex's normal sandbox may write inside the clone, including `config\local\` and
  `data\` (where the fault latch lives). A misbehaving agent could loosen soft limits, DUT profiles or pin maps, or
  clear the latch. You would see it: each run's manifest lists the hash of every configuration file, and
  `uv run b1500 status` shows the current ones. Hard limits can never exceed 42 V / 100 mA. Keep your backup copy of
  `config\local\` and compare when in doubt.
- **Windows specifics.** Claude Code has no sandbox on native Windows; Codex sandboxes the commands it runs, but the
  b1500 server is expected to run outside that sandbox (it has to reach VISA; checked in step 7.4, ATV-4).

**Physical backstop.** Keep the interlock open (v1 never needs more than 42 V; the B1500A then limits outputs to
±42 V in hardware), use per-channel compliance (every recipe sets it) and the closed shield box.

## Optional future hardening (not part of v1)

Both harnesses support an **administrator-managed configuration** that a normal user cannot override: Claude Code
managed settings (for example, disabling the bypass-permissions mode) and Codex managed configuration (for example,
restricting the allowed sandbox and approval modes). That would turn "never use bypass modes" from a habit into an
enforced setting. It needs admin rights on the lab PC, so it is not used in v1 (owner decision D2); check the
current harness documentation before adopting it.

## Recorded results (fill in at deployment)

| Item | Result | Date |
|---|---|---|
| Harness versions (Codex, Claude Code, uv, Git, Python) | | |
| Codex `doctor --summary` sandbox row (step 7.2) | | |
| ATV-4: server opens VISA inside Codex; setting used, if any | | |
| ATV-11: Codex approval prompt shows the summary | | |
| ATV-7: Claude Code prompts in default mode | | |
| ATV-8: Claude Code `/hooks` lists the guard hook | | |
| One-process check (bring-up L0) | | |

# Windows lab PC deployment (v2)

Status: **final for v2 (WP11.4), not yet run on the lab PC**; the owner executes it with the instrument at hand
(M12). What could be checked without the lab PC is checked: the whole simulator gate runs on `windows-latest` in CI
(`.github/workflows/ci.yml`: tests, lint, recipe check, skill lint, card index, coverage page, skill mirror, tool
budget, manual corpus and `b1500 doctor` on backend sim), Windows paths, encodings and the Windows-only code paths
(the WGFMU DLL probe, the registry, the console code page) are tested on every OS by platform injection
(`tests/adapters/test_windows_readiness.py`, `tests/wgfmu_abi/`), and the offline wheelhouse below was built and
installed on the Mac (WP6.5, re-run at the WP11.4 release commit).
Plan of record: blueprint v2 §7 (7.1 kit, 7.4 stages, 7.5 first-session script, since v2.1 the deployment steps
D1-D12 of §"First session" below), §12 owner decisions OD-4, OD-5, OD-7. After the installation the bring-up follows
the stage files and the step sequence of skill `b1500-bringup`; [hardware-bringup.md](hardware-bringup.md) is their
one-page overview.

**The idea in one paragraph.** Everything lives in one folder, the `git clone` of this repository: the Python
environment (`.venv\`), your local configuration (`config\local\`), the run archive and state (`data\`) and the
agent's scratch (`work\`). Nothing needs administrator rights except the VISA driver for the GPIB adapter and the
WGFMU instrument library. Updating means one command, `uv run b1500 update`. The coding agent (Codex, optionally
Claude Code) reaches the B1500A only through the b1500 server; a measurement that needs your consent stops, shows
its summary in the chat and waits for your own words, then the harness asks you once more in its approval prompt.

## First session

Session 0 of the bring-up = the deployment steps D1-D12 of the step sequence
(`.agents/skills/b1500-bringup/steps.yaml`, v2.1; they replace blueprint v2 §7.5's script), then the bring-up
sessions. Each line points to the step of §"Procedure" that explains it; commands run in PowerShell in the clone
folder from D6 on. Lines marked *human* are yours alone: the harness rules and the guard hook stop a coding agent
from running them. Each D step goes into the step ledger once the clone exists: `uv run b1500 bringup next` names
the next one, and you record it in your own terminal (`uv run b1500 bringup done D1 --human "WHAT YOU DID" --by
NAME`; several at once with the `batch done` line `next` prints) or the agent records it from your words in chat
later.

1. **Mac (developer):** push `main` (`git push`, owner decisions OD-4, OD21-11); optionally copy the `1500A`
   manuals folder (~75 MB of PDFs) to the lab PC for figures and `manual build`.
2. **D1** (step 1): Git for Windows; `winget install astral-sh.uv`; `uv python install 3.12`.
3. **D2** (step 1, lab IT): Keysight IO Libraries Suite (the VISA stack) and the GPIB adapter's driver.
4. **D3** (step 1.5, lab IT): **B1530A WGFMU Instrument Library A.03.00 or later** (current A.04.00.2440.5403; its
   installer puts the x64 `wgfmu.dll` into `C:\Windows\System32`).
5. **D4** (step 1.6): Node.js LTS and the Codex CLI from npm (and/or Claude Code as the native build, its
   auto-update off with `DISABLE_AUTOUPDATER=1`), both signed in.
6. **D5** (step 1.7): `setx PYTHONUTF8 1`, then a new PowerShell window.
7. **D6** (step 2): `git clone REMOTE_URL C:\b1500\test_agent`; the manual PDFs in `C:\b1500\` (the clone's parent,
   the default `settings.manuals_dir`) or wherever `B1500_MANUALS_DIR` points.
8. **D7** (steps 3, 5): `uv sync --frozen`; `uv run b1500 manual status` (the committed corpus: 16 documents, 2,315
   pages); *human:* `uv run b1500 config init --visa` (it writes `config\local\` only, no instrument contact; stage L0
   checks it); `uv run b1500 doctor` without FAIL. From here on every step lands in the hardware ledger.
9. **D8** (step 7): `uv run b1500 harness init --codex` (and `--claude`); `uv run b1500 doctor` shows `harness
   files` PASS.
10. **D9** (steps 8.1-8.2, 9.2): start `codex` (and `claude`) in the clone once, trust the project, check the sandbox
    row of `codex doctor --summary`; close it.
11. **D10** (steps 8, 12): *human:* `uv run b1500 update` in your own terminal ends with `Ready.` (it installs the
    validated harness versions); then the maintainer's `uv run b1500 dev harness qualify --windows` once.
12. **D11** (steps 8.5, 9.4-9.5): the interactive checks: the approval prompt shows the summary (or at bring-up L4,
    before the L1 files exist); Claude Code's `/hooks` lists the guard hook.
13. **D12**: the results of §"Recorded results" (versions, WGFMU library, install route) into the ledger.
14. **Sessions 1-8** (step 10; [hardware-bringup.md](hardware-bringup.md)): prompt "Use skill b1500-bringup and
    continue the hardware bring-up from the current stage." The agent works the loop `uv run b1500 bringup next`,
    the step, `uv run b1500 bringup done`: S0 (B1500A: File > Exit EasyEXPERT and leave the "Start EasyEXPERT"
    button on screen; in its Connection Expert GPIB address 17 and System Controller "No"; step 4), L0
    (`uv run b1500 doctor --probe --wgfmu-session`, `uv run b1500 bringup propose-station`; *human:*
    `uv run b1500 config adopt work\bringup\station.proposed.yaml --as station`; pin maps and DUT profiles adopted
    the same way; `uv run b1500 config check`; step 6), then L1-L10. Do the physical steps; consent in chat in your
    own words; approve the harness prompt after comparing its summary.
15. End of each session (step 11; steps E1-E5): `$env:B1500_HW = "1"; uv run pytest -m hardware -rs`; back up
    `data\runs\`; review `work\bringup\records\` into `validation\hw\` and `work\bringup\fixtures\` into
    `tests\fixtures\hw\`; transfer them (OD-7: branch `lab/bringup-<date>` pushed, else a OneDrive copy of
    `work\bringup\`).
16. **Mac (developer):** one developer work package per module: fixture tests, simulator recalibration,
    `hw_validated` promotions from the reviewed records.

## Facts to collect first

Fill in the last column before step 1. Where a fact is unknown, the default applies.

| Fact | Why it matters | Where to find it | Default if unknown | Value |
|---|---|---|---|---|
| GPIB adapter model | Decides the VISA stack; USB adapters may need an even GPIB address (PG PDF 23) | Label on the adapter; Windows Device Manager | Keysight 82357B (USB/GPIB) | |
| VISA vendor, and whether a second VISA is installed | PyVISA loads the system default VISA; two stacks can conflict | Windows "Installed apps": Keysight IO Libraries Suite, NI-VISA | Keysight IO Libraries Suite only; `visa.library: ""` | |
| B1500A GPIB address | `visa.resource` in `config\local\settings.yaml` | B1500A Connection Expert (PG PDF 23) | 17, i.e. `GPIB0::17::INSTR` | |
| WGFMU instrument library version | WGFMU recipes load the x64 `wgfmu.dll` from 64-bit Python (ATV-15) | Windows "Installed apps": "B1530A WGFMU Instrument Library"; the file version of `C:\Windows\System32\wgfmu.dll` | A.04.00 installed by lab IT; `wgfmu.library: ""` (the System32 default) | |
| Internet access (PyPI, harness login and model use) | `uv sync`, `uv python install` and both harnesses need it | Open pypi.org in a browser; ask lab IT about a proxy | Online. The harnesses always need the internet; if only PyPI is blocked see §"Offline wheelhouse" | |
| Offline wheelhouse needed | Only if PyPI is blocked but the harness can still reach its service | Lab IT | Not needed | |
| EasyEXPERT coexistence | EasyEXPERT must be ended while b1500 controls the B1500A (PG PDF 23) | Ask the people who use EasyEXPERT on the instrument; is EasyEXPERT set to auto-start? | Never at the same time: EasyEXPERT ended (File > Exit, Start EasyEXPERT button left on screen) whenever b1500 works | |
| Harness choice and versions | Behaviour of approvals and rules depends on the version | `codex --version`, `claude --version`, `uv --version`, `git --version` | Codex only, at the version in `config/harness/validated.yaml` (`uv run b1500 update` installs it); Claude Code optional, same file | |
| Node.js LTS | npm is the one install method of Codex | `node --version` | Node.js LTS from WinGet (`OpenJS.NodeJS.LTS`), per user | |
| Manuals folder | Figures and `manual build` need the PDFs; search and page text come from the committed corpus | Copy of the developer's `1500A` folder | `C:\b1500\` (the clone's parent), or set `B1500_MANUALS_DIR` | |
| Backup of `data\runs\` | Runs exist only in the clone | Ask the owner: target folder and rhythm | No automatic backup; copy `data\runs\` and `config\local\` at the end of each measurement day (step 11) | |
| Clone folder | Long or non-ASCII paths cause Windows path problems; `doctor` warns above 80 characters | Choose | `C:\b1500\test_agent` | |
| Windows account and admin rights | The VISA and WGFMU installers need admin rights once | Lab IT | Lab IT installs both; everything else installs per user without admin rights | |
| Power-line frequency | Run-time estimates and integration assume 50 Hz (ATV-31) | EasyEXPERT Configuration window, Main Frame tab | 50 Hz | |
| Git remote, branch and credentials | What `git clone` and `uv run b1500 update` fetch; pushing the bring-up records (OD-7) needs credentials | The developer | The developer's remote, its default branch `main`; no push credentials: OneDrive copy | |

## Procedure

Run every command in **PowerShell**, in the clone folder from step 2 on. Native Windows only, not WSL (a Linux
process cannot load the vendor VISA DLL, the WGFMU library or see the USB/GPIB adapter).

### Step 1 — Install the prerequisites (once)

1. **Git for Windows** (a per-user install is fine). Claude Code also needs it for its Bash tool.
2. **uv**, without admin rights: `winget install astral-sh.uv` (or
   `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`). Open a new PowerShell
   window and check `uv --version`.
3. **Python 3.12 x64** through uv: `uv python install 3.12` (kept in uv's own folder, no admin rights).
4. **VISA stack and GPIB adapter driver — one vendor only:** Keysight IO Libraries Suite with a Keysight 82357B
   (the lab's stack), or NI-VISA with NI-488.2 and an NI GPIB-USB-HS. Admin rights, usually lab IT. Check: Keysight
   Connection Expert lists the instrument at `GPIB0::17::INSTR` once EasyEXPERT is ended (step 4).
5. **B1530A WGFMU Instrument Library A.03.00 or later** (the free Keysight download; current
   A.04.00.2440.5403). Install the 64-bit library: the x64 `wgfmu.dll` goes to `C:\Windows\System32`, which is
   where `settings.wgfmu.library: ""` looks; a different path goes into `wgfmu.library` (ATV-15 fallback). 64-bit
   Python cannot load a 32-bit DLL, and there is no 32-bit bridge. Admin rights, usually lab IT.
6. **Coding harness, one install method each** (no admin rights). The exact versions come later from
   `config/harness/validated.yaml`, which `uv run b1500 update` installs (step 12); harness versions change only
   when the maintainer has qualified a new one and committed it there.
   - **Codex from npm:** install Node.js LTS (`winget install OpenJS.NodeJS.LTS`), open a new PowerShell window,
     run `npm install -g @openai/codex`, then `codex login`. Codex installed this way never updates itself;
     decline its "update available" offer.
   - **Claude Code (optional) as the native build:** `irm https://claude.ai/install.ps1 | iex`, sign in with
     `claude auth login`, and turn its auto-update off on the lab PC: add `"env": {"DISABLE_AUTOUPDATER": "1"}` to
     `%USERPROFILE%\.claude\settings.json` (or `setx DISABLE_AUTOUPDATER 1`). Never set `DISABLE_UPDATES`: it
     also blocks `claude install`, which `update` uses.
   - Another install method (WinGet or Homebrew packages, a downloaded binary, Claude Code through npm) is reported
     by `uv run b1500 update` with the one-time switch command.
7. **UTF-8 mode for Python:** `setx PYTHONUTF8 1` (user environment; takes effect in new windows). Manual pages,
   units (`Ω`, `µ`) and run notes are UTF-8: without it Python writes redirected output in the ANSI code page
   (cp1252, or cp936 on a Chinese Windows). The `b1500` commands then print `\u03a9`-style escapes instead of
   failing, the generated harness configs set it for the server anyway, and `doctor` warns while it is missing.

pip instead of uv is possible for the command line only: §"Offline wheelhouse" builds the locked package list; on
the lab PC (Python 3.12 x64 from python.org, per-user install) create `.venv` with `python -m venv .venv` and
install with `.venv\Scripts\python -m pip install -r requirements-win.txt` and
`.venv\Scripts\python -m pip install --no-deps -e .`. The generated harness configs and the Claude Code hook start
`uv`, so the agents need uv.

### Step 2 — Get the code and the manuals

```powershell
git clone REMOTE_URL C:\b1500\test_agent
cd C:\b1500\test_agent
git status
```

`REMOTE_URL` comes from the facts table; the clone is on the default branch `main`, the one `uv run b1500 update`
pulls (step 12). Line endings are handled by the committed `.gitattributes` (every text file LF on every clone, so
the plan hashes of committed files are the same as on the Mac). Keep the clone path short and ASCII: `doctor` warns
above 80 characters, because a run folder path must still fit the classic 260-character Windows limit.

**Manuals (optional).** `b1500 manual search`, `page` and `toc` read the committed page corpus and need no PDF.
Only figures and `manual build` need the PDFs: copy the developer's `1500A` folder content (the PDFs, `Demo\`,
`lwp\matlab_B1500\9018-01706.pdf`) into `C:\b1500\`, the clone's parent (the default `settings.manuals_dir: ".."`),
or anywhere else and point `B1500_MANUALS_DIR` there (`setx B1500_MANUALS_DIR D:\manuals\1500A`).

### Step 3 — Install the dependencies

```powershell
uv sync --frozen
uv run b1500 --help
uv run b1500 manual status
uv run b1500 doctor
```

`uv sync --frozen` creates `.venv\` inside the clone exactly as `uv.lock` says. `manual status` must say
`corpus current: 16 docs, 2315 pages`; PDFs found or not is only information. `doctor` runs on backend `sim`
(no instrument yet): no FAIL line; until step 7 "harness files" is a WARN, and "harness versions" until
`uv run b1500 update` installed the validated harness versions (step 10); `wgfmu library` PASSes once the x64 DLL
is installed (step 1.5), WARNs while it is missing; `local config` PASSes on the committed examples;
`LongPathsEnabled` may WARN (keep the clone path short instead of changing the registry); `PYTHONUTF8` WARNs in a
window opened before step 1.7.

**PyPI blocked:** install from a wheelhouse instead (§"Offline wheelhouse"), then continue with `manual status`.

### Step 4 — Hand the B1500A over from EasyEXPERT

Bring-up stage S0 (session 1, after the deployment steps D1-D12;
[s0-physical](../.agents/skills/b1500-bringup/stages/s0-physical.md)) in short: interlock and
shield box checked, cables recorded, EasyEXPERT reference files saved. On the B1500A: **File > Exit EasyEXPERT**
and leave the "Start EasyEXPERT" button on screen (EasyEXPERT and b1500 never control the instrument at the same
time); in the B1500A's Keysight Connection Expert set GPIB address **17** and System Controller **No**.

### Step 5 — Create the local configuration (human)

Deployment step D7 (session 0: no instrument contact yet; bring-up L0 checks the result). These commands are yours alone: the harness rules and the guard hook stop a coding agent
from running `config init` and `config adopt` (§"Harness permissions" below).

```powershell
uv run b1500 config init --visa
uv run b1500 config check
```

`config init --visa` copies the missing `config\{settings,station,policy}.example.yaml` to `config\local\` (it never
overwrites an existing file), writes `backend: visa` into the settings file it creates and creates the empty
`config\local\pinmaps\` and `config\local\duts\` folders. Then edit the copies (you, not the agent; the agent is never
allowed to edit `config\local\`):

- `settings.yaml`: `visa.resource` from the facts table; `visa.library` only when two VISA stacks are installed;
  `wgfmu.library` only when the DLL is not in System32; keep the `\n` terminations (checked at bring-up L0, ATV-2).
- `station.yaml`: leave the modules as they are for now: step 6 proposes them from the live inventory. Record
  `interlock.available` (stays `null` until the bring-up Stage 0 test) and the cables in `topology`.
- `policy.yaml`: keep the defaults. You may only tighten them; anything above 42 V or 100 mA makes the configuration
  invalid.
- `pinmaps\` and `duts\`: adopted stage by stage during the bring-up from the examples, for example
  `uv run b1500 config adopt config\pinmaps\mosfet-3t-lab.example.yaml --as pinmap` (it validates the file, shows
  the diff, keeps a previous local file as `.bak` and copies it in with LF line ends, also when Notepad saved it
  with CRLF); keep `certainty: unverified` until you checked the wiring. Example pin maps and DUT profiles are
  never used with `backend: visa`. Never name a local file `*.example.yaml`.

`uv run b1500 config check` must say `config: valid` with backend `visa` because of `config\local\settings.yaml`.
From now on `doctor`'s `local config` line lists what only you can record and WARNs while a plan would stay blocked
without it: no pin map or DUT profile in `config\local\` yet; a `null` input or unknown presence on a switch a local
pin map routes through (record the cabling at L6–L8, or delete an input side that is not cabled); a pin-map terminal
the SPGU, the WGFMU or the MFCMU can reach without a `pulse` or `ac` envelope in a DUT profile that fits the
landing. It is the checklist of the configuration work of the bring-up; at the end of L8 it should PASS.

### Step 6 — Probe the instrument and adopt the station

Bring-up stage L0 (session 1: the agent probes and proposes, you adopt); prerequisite: step 4 done (EasyEXPERT
ended).

```powershell
uv run b1500 doctor
uv run b1500 doctor --probe --wgfmu-session
uv run b1500 bringup propose-station
uv run b1500 config adopt work\bringup\station.proposed.yaml --as station
uv run b1500 config check
uv run b1500 doctor --probe --wgfmu-session
```

- `doctor`: no FAIL line. Its `wgfmu library` line locates `wgfmu.dll` (`wgfmu.library`, default
  `C:\Windows\System32\wgfmu.dll`) and reads its header without loading it: PASS for the x64 DLL with every function
  the binding needs (file version shown); FAIL "install library >= A.03.00" for a 32-bit DLL (64-bit Python cannot
  load it; there is no 32-bit bridge) and, on backend visa with a WGFMU, for a missing one.
- `doctor --probe` is read-only (queries only, never `CN` or any setting command): the VISA library loads and
  `list_resources()` lists `visa.resource`; the bus opens with the exclusive lock; `*IDN?` names the B1500A
  (firmware recorded); `UNT?` against `config\local\station.yaml`; the error queue is drained; status byte; every
  output off (`LOP?`); the 16440A selector mode and outputs; `SPST?` with an SPGU installed; `CORRST?`/`ADJ?` per
  MFCMU; then unlock and close; then `wgfmu library` (as in `doctor`) and, with `--wgfmu-session`, the library's own
  session with the GPIB link closed: open, channel ids (the WGFMU channels `UNT?` lists, e.g. 201 and 202), status
  (no sequencer running), close (ATV-16: no output changes). One PASS/INFO/WARN/FAIL line each (`--json` for the full
  report), exit code 1 on any FAIL, and every raw answer in `work\bringup\probe-<UTC>.json`. The first run usually
  FAILs `inventory` (the station file is still the example) and may WARN about old errors in the queue.
- `bringup propose-station` reads `*IDN?` and `UNT?` (read-only) and writes `work\bringup\station.proposed.yaml`: the
  live module list with the example's aliases and its switch wiring left `null`/`certainty: unverified`. It prints
  the diff against `config\local\station.yaml`. Fill in the selector and RSU inputs only once you know the cabling
  (bring-up L7), then adopt the file yourself with `config adopt … --as station` (validates, shows the diff, keeps
  the old file as `station.yaml.bak`).
- The second `doctor --probe` must show no FAIL. [hardware-bringup.md](hardware-bringup.md) and the stage file L0
  are the full version of this step.

### Step 7 — Wire the harness

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

### Step 8 — Launch Codex and check it

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
   documentation for MCP servers that need device access and record the setting (L0.A6 `server_visa`,
   §"Recorded results").
5. **ATV-11 check (the approval prompt shows the summary).** Needs the DUT disconnected and the two L1 files of the
   bring-up (`open-smus` pin map, `open-circuit` DUT profile; create them now as the L1 stage file describes, or do
   this check when you reach L1). Ask: "Validate system.zero_check on pin map open-smus with DUT profile
   open-circuit, then run it." Expected: the agent shows the plan summary, says it needs
   your confirmation and stops. Reply "Confirmed, go ahead". Codex's approval prompt for `run_confirmed_plan` must
   show the `summary` argument; compare it, then **decline** (nothing is sent to the instrument). Fallback if the
   prompt hides the arguments: approve real runs only after comparing the summary the agent printed in the chat (the
   skill makes it print the summary verbatim; acceptance scenario S4 checks that); record it.
6. Codex may stay open while you use the command line: an idle b1500 MCP server holds no VISA session
   ([hardware-bringup.md](hardware-bringup.md), "CLI and harness coexist").

### Step 9 — Claude Code (optional)

1. `claude --version` is the version in `config/harness/validated.yaml` (`uv run b1500 update` installs it; the
   hook's fail-closed setting needs 2.1.295 or later) and `uv` is on `PATH`: the guard hook runs through `uv`, and
   if it cannot start, every shell and file-edit call of Claude Code is blocked until it is fixed.
2. Start `claude` in the clone root and **approve the project MCP server `b1500` once** when asked. Check:
   `claude mcp list` shows `b1500` connected (before the approval it says "Pending approval").
3. Use the default permission mode (accept-edits is fine). Never use `--dangerously-skip-permissions`, never set
   `"defaultMode": "bypassPermissions"` in `%USERPROFILE%\.claude\settings.json` or `.claude\settings.local.json`.
   Claude Code has no sandbox on native Windows, so its deny rules and the hook are the second layer.
4. **ATV-8 check (hook active).** In Claude Code, `/hooks` lists the `PreToolUse` hook
   `scripts/hooks/b1500_guard.py` for Bash, PowerShell, Write, Edit, MultiEdit and NotebookEdit. Whether hooks also
   run in bypass-permissions mode is not verified; fallback: that mode is never used here (accepted residual, D3),
   and the deny rules hold in every mode.
5. **ATV-7 and ATV-11 check.** Repeat the request of step 8.5. The `run_confirmed_plan` prompt must appear in the
   default mode and show the `summary`; decline it. Fallback (ATV-7): the `requiresUserInteraction` flag (policy
   `confirmation.claude_require_user_interaction: true`, the default) forces the prompt; if no prompt appears at all,
   do not use Claude Code with the instrument and record it.

### Step 10 — Bring the instrument up with the agent

First, with every harness closed, run `uv run b1500 update` in PowerShell: it must end with `Ready.` (otherwise do
its numbered list; step 12). Then start the harness in the clone root and give it this prompt:

> Use skill b1500-bringup and continue the hardware bring-up from the current stage.

The agent works step by step: `uv run b1500 bringup next` names the step (after a break first the session-start
steps R1-R4 and what to confirm again), the agent does it or hands it to you, and `uv run b1500 bringup done`
verifies and records it in the step ledger with your own words for your steps (the steps one message of yours
confirmed and the agent's finished steps next to them go in one call, each still verified and recorded on its own).
It tells you the physical steps, probes and proposes, and runs validated plans only after your consent in chat; you
do the physical steps, consent in your own words and approve the harness prompt after comparing its summary with the
chat. The stages, the nine sessions and who does what: [hardware-bringup.md](hardware-bringup.md).

**Long runs and the harness.** A plan longer than 5 min runs asynchronously in the b1500 server; the agent polls
`get_run` and stops it with `safe_shutdown`. The server lives as long as the harness keeps it: in the interactive
`codex` (and `claude`) session it stays up between turns. Headless `codex exec` (codex-cli 0.170.0) ends the server
at every turn end without its shutdown hook, which kills a running run: the outputs stay on until the next call's
`safe_shutdown` recovers it as `aborted` (WP7.7). Claude Code ends its server with SIGTERM, which cancels the run at
its next checkpoint (`cancelled`, cleanup verified). So run long plans from the interactive harness, keep it open
until the run has ended, and end every session with `safe_shutdown` (or `uv run b1500 shutdown --reason "end of
session"` in your own window); bring-up L9 drills both a cancel and a kill per bus, and L10 records how the lab's
harness versions end the server ([safety-model.md](safety-model.md), "Residual risks (v2)").

### Step 11 — End of the measurement day

```powershell
$env:B1500_HW = "1"; uv run pytest -m hardware -rs
uv run b1500 bringup status
robocopy data\runs D:\b1500-backup\runs /E
robocopy config\local D:\b1500-backup\config-local /E
```

1. **Hardware suite.** Without `B1500_HW=1` every hardware test only skips; with it the read-only probe checks and
   the record checks run against the instrument (backend visa). `-rs` lists the skips with their reasons.
2. **Backup** (target from the facts table) of the run archive and your configuration.
3. **Review the drafts.** `bringup status` lists the stages and their records. Check every draft in
   `work\bringup\records\` against its raw runs, fill `reviewer` and `reviewed_on`, and move it to the name in its
   header under `validation\hw\`; move the fixtures you accept from `work\bringup\fixtures\` to
   `tests\fixtures\hw\` ([validation/hw/README.md](../validation/hw/README.md)). Nothing in `validation\hw\` or
   `tests\fixtures\hw\` ever comes from a simulator run.
4. **Transfer (OD-7).** With git push credentials on the lab PC:

   ```powershell
   git switch -c lab/bringup-2026-12-01
   git add validation/hw tests/fixtures/hw
   git commit -m "Bring-up records of 2026-12-01"
   git push -u origin lab/bringup-2026-12-01
   ```

   (today's date in the branch name). Without credentials copy `work\bringup\` and `validation\hw\` to the shared
   OneDrive folder. The developer then promotes the recipes on the Mac (blueprint v2 §7.2).

### Step 12 — Daily use and updates

- Each measurement day: the interlock test of bring-up Stage 0 (the User Guide asks for it daily, UG PDF 142),
  EasyEXPERT ended, then `uv run b1500 status` (an open harness does not block it), or `station_status` through the
  agent.
- **CLI and harness coexist:** every b1500 call opens and closes the instrument's VISA session, so the CLI works
  while a harness is open; only EasyEXPERT or another VISA program that keeps the instrument makes calls answer
  `busy` (details: [hardware-bringup.md](hardware-bringup.md), "CLI and harness coexist").
- Human-only commands, typed by you, never by the agent: `uv run b1500 run --confirm PLAN_ID`,
  `uv run b1500 fault clear --by NAME` (only after a verified `uv run b1500 shutdown`), `uv run b1500 config init`
  and `uv run b1500 config adopt`.
- **Update:** close every harness window, then type, yourself:

  ```powershell
  uv run b1500 update
  ```

  It pulls `main` (`git pull --ff-only`), runs `uv sync --frozen` and continues with the pulled code, re-renders a
  drifted `.codex\config.toml` / `.mcp.json`, brings each installed harness to the version in
  `config/harness/validated.yaml` (it asks first, then runs the one installer:
  `npm install -g @openai/codex@<version>`, `claude install <version>`), checks the hold of the versions on this PC
  (Claude Code's auto-update off), runs the free checks (signed in, no bypass default in your harness configs,
  Claude Code accepts `.claude\settings.json`, Codex forbids the eight human-only commands, both harnesses trust the
  clone, the b1500 server starts with its ten tools, `uv run b1500 doctor` without FAIL) and ends with `Ready.` or
  `Not ready. Do this:` and a numbered list. Lines starting with `note:` block nothing.
  - It changes nothing it cannot finish: a changed tracked file, another branch (for example `lab/bringup-…` after a
    transfer: `git switch main`), local commits that diverged from origin, or no network stop it with one plain
    message. `git pull` never touches `config\local\` or `data\` (both are ignored by git).
  - `uv run b1500 update --check` shows the same verdict and changes nothing (no pull, sync or install).
  - It refuses to run inside a Codex or Claude Code session or without a terminal: type it yourself.
  - A new harness version reaches this PC only through `validated.yaml`, after the maintainer qualified it on the
    Mac (`uv run b1500 dev harness qualify`, [acceptance/README.md](acceptance/README.md)); `uv run b1500 doctor`
    warns at every session start while an installed harness differs ("run `uv run b1500 update`"). After a version
    change repeat the interactive checks of steps 8.2, 8.5 and, for Claude Code, 9.4–9.5 (they cannot be checked
    without you), and the maintainer runs `uv run b1500 dev harness qualify --windows` once on this PC (T0, the
    probes and S16 on the simulator, about 0.5–0.8 USD and 0.4–0.6 M Codex tokens; `update` notes it until then).
  - With a wheelhouse install (`UV_OFFLINE`), an update that changes `uv.lock` stops with "a new wheelhouse is
    needed" (§"Offline wheelhouse").

## Offline wheelhouse

Only when the lab PC cannot reach PyPI (the harnesses still need their own service). The Python packages travel as
a folder of wheels built on any PC with internet, here the Mac, from a clone of the commit the lab PC runs.

**On the Mac** (bash, in the clone; `uvx` runs pip without installing it):

```bash
uv export --frozen --no-hashes --no-emit-project --output-file requirements.txt
uv pip compile requirements.txt --no-deps --python-platform x86_64-pc-windows-msvc --python-version 3.12 \
  --no-annotate --no-header --output-file requirements-win.txt
uvx --from pip pip download --only-binary=:all: --platform win_amd64 --python-version 3.12 --implementation cp \
  --abi cp312 --no-deps -r requirements-win.txt -d wheelhouse
uvx --from pip pip download --only-binary=:all: --platform win_amd64 --python-version 3.12 --implementation cp \
  --abi cp312 --no-deps "setuptools>=69" wheel -d wheelhouse
UV_CACHE_DIR=empty-cache uv pip install --offline --no-index --find-links wheelhouse \
  --python-platform x86_64-pc-windows-msvc --python-version 3.12 --target wheelhouse-check -r requirements-win.txt
```

- `uv export` writes every locked package, the dev group included (the lab PC runs the hardware suite with pytest).
- `uv pip compile --no-deps` evaluates the environment markers for Windows: `pip download` evaluates them on the
  machine it runs on, so without this step the Windows-only `colorama` and `pywin32` would be missing.
- `setuptools` and `wheel` are the build backend of the editable install of the clone itself.
- The last command is the check: it installs the whole list for Windows x64 from the wheelhouse alone, with an empty
  cache and no network. Delete `wheelhouse-check\` afterwards; never commit wheels.

Checked on the Mac (WP6.5; re-run at the WP11.4 release commit, `uv.lock` unchanged since WP9.6): 98 wheels (96
packages + `setuptools` + `wheel`), 81 MB (85.1 million bytes), the largest `numpy` (12.6 MB), 21 `win_amd64` and 77
pure-Python wheels; the check above installed all 96 packages for `x86_64-pc-windows-msvc`, and the clone itself
built from the wheelhouse alone. The lab-PC sequence below was rehearsed on macOS with a macOS wheelhouse (WP11.4:
96 wheels, 66 MB): after the two `uv pip install` commands, `uv sync --frozen` with `UV_OFFLINE=1` and an empty uv
cache reported all 95 packages present and installed nothing, and `uv run` worked offline (`doctor` without FAIL,
`manual status` current, `pytest`). Downloads of the re-run: 147 MB, no file above 13 MB.

**On the lab PC** (PowerShell; `wheelhouse\` and `requirements-win.txt` copied next to the clone, `uv.exe` from
the uv release zip on `PATH`, Python 3.12 x64 from step 1 or the python.org installer):

```powershell
setx UV_OFFLINE 1
uv venv --python 3.12
uv pip install --python .venv --no-index --find-links ..\wheelhouse -r ..\requirements-win.txt
uv pip install --python .venv --no-index --find-links ..\wheelhouse --no-deps -e .
uv sync --frozen
uv run b1500 manual status
```

`setx UV_OFFLINE 1` (new windows) keeps every later `uv` call, the harness's `uv run` included, off the network;
`uv sync --frozen` then only confirms that `.venv\` matches `uv.lock`. Continue with step 3 from `manual status`.

## Harness permissions

Owner decision OD-5 (blueprint v2 §12, decided 2026-11-18): the configuration bootstrap is the human's, read-only
manual and bring-up commands need no approval. Owner decision OD21-6 (v2.1 plan §9, decided 2026-11-26): the three
step-ledger commands `bringup next|done|check` need no approval either. Coding agents may never edit
`.claude/settings*.json` or `.codex/**` (both are edit-denied), so each change set was applied once by the
orchestrator, exactly as written here, with the shell (OD-5 at WP6.1, OD21-6 at WP21.5); the applied diffs are
logged in `docs/design/progress.md` (WP6.1 and WP21.5 rows).
`b1500 harness init --codex --claude --check` and `b1500 doctor` check that the files carry these lines
(`devtools/harness.py`), and
`tests/adapters/test_harness_permissions.py` asserts the applied state. Nobody adds other lines without a new owner
decision.

**Claude Code, `.claude/settings.json`.** `permissions.deny` gains (the human-only bootstrap, with and without
`uv run`):

```json
"Bash(b1500 config init*)",
"Bash(uv run b1500 config init*)",
"Bash(b1500 config adopt*)",
"Bash(uv run b1500 config adopt*)"
```

`permissions.allow` gains (read-only commands of the manual corpus and the bring-up helpers; nothing else is
allowed without asking):

```json
"Bash(uv run b1500 manual *)",
"Bash(uv run b1500 bringup status*)",
"Bash(uv run b1500 bringup propose-station*)",
"Bash(uv run b1500 bringup capture*)",
"Bash(uv run b1500 bringup record*)"
```

and, by OD21-6, the step-ledger commands (`next` reads, `done` verifies the evidence and appends to the CLI-written
ledger under `data/state/bringup/`, `check` re-verifies it; none of them sends anything to the instrument):

```json
"Bash(uv run b1500 bringup next*)",
"Bash(uv run b1500 bringup done*)",
"Bash(uv run b1500 bringup check*)"
```

**Codex, `.codex/rules/b1500.rules`.** Four `forbidden` prefix rules, each with `match`/`not_match` examples that
Codex verifies when it loads the file, like the existing rules:

| `pattern` | `match` | `not_match` |
|---|---|---|
| `["b1500", "config", "init"]` | `b1500 config init --visa` | `b1500 config check` |
| `["uv", "run", "b1500", "config", "init"]` | `uv run b1500 config init --visa` | `uv run b1500 config check` |
| `["b1500", "config", "adopt"]` | `b1500 config adopt work/bringup/station.proposed.yaml --as station` | `b1500 bringup propose-station` |
| `["uv", "run", "b1500", "config", "adopt"]` | the same with `uv run` | `uv run b1500 bringup propose-station` |

Justifications: creating `config/local/` is the human's act (the agent proposes with
`b1500 bringup propose-station`); adopting a file into `config/local/` is the human's act after reviewing the
proposal and its diff.
Codex runs `uv run b1500 manual …` and `uv run b1500 bringup …` in its default `workspace-write` sandbox without a
rule (ATV-25).

**Templates.** `config/harness/` holds only the MCP server launch templates (`codex.config.toml`, `mcp.json`); they
carry no permission rules, so nothing changes there. **Guard hook.** `scripts/hooks/b1500_guard.py` (tightened by
WP6.1, no settings change needed) also blocks shell commands that run `b1500 config init` or `b1500 config adopt`,
with or without `uv run`, for Claude Code in every permission mode the hook runs in.

`uv run b1500 update` checks both after every pull (the wiring, and `codex execpolicy check` of the eight forbidden
commands). By hand: `uv run b1500 harness init --codex --check` (and `--claude`) and
`codex execpolicy check --rules .codex/rules/b1500.rules uv run b1500 manual search x` (no decision = not matched).

## Residual risks in plain words

**What the software guarantees in normal use.** A measurement that needs your consent runs only after you approve
it in the harness prompt, which shows the plan summary. The agent cannot run such a plan through the ordinary run
tool, and a blocked plan cannot run from the chat at all. Whatever is approved or configured, the library never
goes above 42 V or 100 mA, stays within each module's ratings and checks every output command against the plan.
Every run records what was approved and the fingerprints (sha256) of the configuration files it used.

**What it does not guarantee (accepted by the owner, decision D3):**

- **Approvals switched off.** If Codex runs with full access, `--yolo` or approval `never`, or Claude Code in bypass
  mode, the agent can approve its own measurements. Codex then does not ask at all; Claude Code still asks for
  `run_confirmed_plan` because the tool is flagged to always need you. Keep the default modes (steps 8 and 9).
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
  b1500 server is expected to run outside that sandbox (it has to reach VISA; checked in step 8.4, ATV-4).

**Physical backstop.** Keep the interlock open (the kernel never goes above 42 V; the B1500A then limits outputs to
±42 V in hardware), use per-channel compliance (every recipe sets it) and the closed shield box.

## Optional future hardening (not part of v2)

Both harnesses support an **administrator-managed configuration** that a normal user cannot override: Claude Code
managed settings (for example, disabling the bypass-permissions mode) and Codex managed configuration (for example,
restricting the allowed sandbox and approval modes). That would turn "never use bypass modes" from a habit into an
enforced setting. It needs admin rights on the lab PC, so it is not used here (owner decision D2); check the
current harness documentation before adopting it.

## Recorded results (in the step ledger)

What the deployment and the bring-up find out about this PC is recorded in the step ledger, not on this page: each
result is an `--observe KEY=VALUE` (or the human's own words) of the step that settles it, written only by
`uv run b1500 bringup done` to `data\state\bringup\ledger-visa.jsonl` with its time and evidence;
`uv run b1500 bringup check --all` re-verifies it, and the stage records embed their stage's steps, so the results
travel with the records (OD-7). Where each result lands:

| Item | Step and key |
|---|---|
| Harness versions (Codex, Claude Code: = `config/harness/validated.yaml`), uv, Git, Python, Node.js | D12 `versions` |
| `uv run b1500 update`: verdict `Ready.`; install methods (Codex npm, Claude Code native); Claude Code auto-update off | D10 `update`; D4 (your words) |
| The maintainer's `uv run b1500 dev harness qualify --windows` (T0, T1, S16) | D10 `qualify_windows` |
| WGFMU instrument library version and DLL path (ATV-15) | D12 `wgfmu_library`; L0's `wgfmu_library` probe line and its `wgfmu_version` fixture |
| Install route: PyPI or wheelhouse (commit it was built from) | D12 `install_route` |
| Trust of the project and the Codex `doctor --summary` sandbox row (steps 8.1-8.2) | D9 `trusted`, `sandbox` |
| ATV-4: server opens VISA inside the harness; setting used, if any | L0.A6 `server_visa` (check `server_visa`) |
| ATV-11: the approval prompt shows the summary | D11 `approval_prompt`; L4.P4 (check `approval_prompt`) |
| ATV-7: Claude Code prompts in default mode | L4.P4 `prompt_shown` |
| ATV-8: Claude Code `/hooks` lists the guard hook | D11 `hooks_listed`; L10.P3 (check `hooks_listed`) |
| One-process check (bring-up L0) | L0.P4 `one_process` |
| `doctor` `local config` PASS (end of L8) | L8.A10 `local_config` |
| How Codex / Claude Code end the server when a session closes during a long run (L10) | L10.A2 `outcomes` (check `session_end_async`) |

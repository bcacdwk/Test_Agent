# Windows lab PC deployment (v2)

Status: **checklist, not yet run on the lab PC**; the owner executes it with the instrument at hand (M12). What
could be checked without the lab PC is checked: the whole simulator gate runs on `windows-latest` in CI
(`.github/workflows/ci.yml`: tests, lint, recipe check, skill lint, card index, skill mirror, tool budget, manual
corpus), Windows paths, encodings and the Windows-only code paths are tested on every OS by platform injection
(`tests/adapters/test_windows_readiness.py`), and the offline wheelhouse below was built and installed on the Mac.
Plan of record: blueprint v2 §7 (7.1 kit, 7.4 stages, 7.5 first-session script = §"First session" below), §12
owner decisions OD-4, OD-5, OD-7. After the installation the bring-up follows the stage files of skill
`b1500-bringup`; [hardware-bringup.md](hardware-bringup.md) is their one-page overview.

**The idea in one paragraph.** Everything lives in one folder, the `git clone` of this repository: the Python
environment (`.venv\`), your local configuration (`config\local\`), the run archive and state (`data\`) and the
agent's scratch (`work\`). Nothing needs administrator rights except the VISA driver for the GPIB adapter and the
WGFMU instrument library. Updating means `git pull`. The coding agent (Codex, optionally Claude Code) reaches the
B1500A only through the b1500 server; a measurement that needs your consent stops, shows its summary in the chat
and waits for your own words, then the harness asks you once more in its approval prompt.

## First session

Blueprint v2 §7.5, in order. Each line points to the step of §"Procedure" that explains it; commands run in
PowerShell in the clone folder from line 4 on. Lines marked *human* are yours alone: the harness rules and the
guard hook stop a coding agent from running them.

1. **Mac (developer):** push the release branch (`git push`, owner decision OD-4); optionally copy the `1500A`
   manuals folder (~75 MB of PDFs) to the lab PC for figures and `manual build`.
2. **Lab PC, once** (step 1): Git for Windows; `winget install astral-sh.uv`; `uv python install 3.12`; Keysight
   IO Libraries Suite (lab IT; the VISA stack); **B1530A WGFMU Instrument Library A.03.00 or later** (current
   A.04.00.2440.5403; its installer puts the x64 `wgfmu.dll` into `C:\Windows\System32`); the Codex CLI (and/or
   Claude Code); `setx PYTHONUTF8 1`.
3. `git clone REMOTE_URL C:\b1500\test_agent` (step 2); the manual PDFs in `C:\b1500\` (the clone's parent, the
   default `settings.manuals_dir`) or wherever `B1500_MANUALS_DIR` points.
4. `uv sync --frozen`; `uv run b1500 manual status` (the committed corpus: 16 documents, 2,315 pages);
   `uv run b1500 doctor` (PASS/WARN only, backend still `sim`) (step 3).
5. B1500A: File > Exit EasyEXPERT and leave the "Start EasyEXPERT" button on screen; in its Connection Expert
   GPIB address 17 and System Controller "No" (step 4; bring-up stage S0).
6. *human:* `uv run b1500 config init --visa` (step 5); then `uv run b1500 doctor --probe`: PASS lines
   (step 6). The WGFMU library session check of the probe (`--wgfmu-session`) arrives with the WGFMU work package
   (WP10.2); until then stage L8 checks the library.
7. `uv run b1500 bringup propose-station`; fill the selector and RSU inputs from the cabling; *human:*
   `uv run b1500 config adopt work\bringup\station.proposed.yaml --as station`; pin maps and DUT profiles from
   the examples, adopted the same way; `uv run b1500 config check` (step 6).
8. `uv run b1500 harness init --codex`; start `codex` in the clone and trust the project (steps 7 and 8).
9. Prompt: "Use skill b1500-bringup and continue the hardware bring-up from the current stage." Do the physical
   steps; consent in chat in your own words; approve the harness prompt after comparing its summary (step 10).
10. End of day (step 11): `$env:B1500_HW = "1"; uv run pytest -m hardware -rs`; back up `data\runs\`; review
    `work\bringup\records\` into `validation\hw\` and `work\bringup\fixtures\` into `tests\fixtures\hw\`;
    transfer them (OD-7: branch `lab/bringup-<date>` pushed, else a OneDrive copy of `work\bringup\`).
11. **Mac (developer):** one developer work package per module: fixture tests, simulator recalibration,
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
| Harness choice and versions | Behaviour of approvals and rules depends on the version | `codex --version`, `claude --version`, `uv --version`, `git --version` | Codex only; the versions of the latest acceptance report in `docs/acceptance/` or newer; Claude Code at least 2.1.295 | |
| Manuals folder | Figures and `manual build` need the PDFs; search and page text come from the committed corpus | Copy of the developer's `1500A` folder | `C:\b1500\` (the clone's parent), or set `B1500_MANUALS_DIR` | |
| Backup of `data\runs\` | Runs exist only in the clone | Ask the owner: target folder and rhythm | No automatic backup; copy `data\runs\` and `config\local\` at the end of each measurement day (step 11) | |
| Clone folder | Long or non-ASCII paths cause Windows path problems; `doctor` warns above 80 characters | Choose | `C:\b1500\test_agent` | |
| Windows account and admin rights | The VISA and WGFMU installers need admin rights once | Lab IT | Lab IT installs both; everything else installs per user without admin rights | |
| Power-line frequency | Run-time estimates and integration assume 50 Hz (ATV-31) | EasyEXPERT Configuration window, Main Frame tab | 50 Hz | |
| Git remote, branch and credentials | What `git clone` and `git pull` fetch; pushing the bring-up records (OD-7) needs credentials | The developer | The developer's remote, branch `rearch/v2` until it is merged; no push credentials: OneDrive copy | |

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
6. **Coding harness:** the Codex CLI for Windows (native, PowerShell, sign in once). Optional: Claude Code with
   `irm https://claude.ai/install.ps1 | iex` (no admin rights) and sign in.
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
git clone --branch rearch/v2 REMOTE_URL C:\b1500\test_agent
cd C:\b1500\test_agent
git status
```

`REMOTE_URL` and the branch come from the facts table. Later updates use `git pull` (step 12). Line endings are
handled by the committed `.gitattributes` (every text file LF on every clone, so the plan hashes of committed files
are the same as on the Mac). Keep the clone path short and ASCII: `doctor` warns above 80 characters, because a
run folder path must still fit the classic 260-character Windows limit.

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
(no instrument yet): no FAIL line; until step 7 "harness files" is a WARN; `LongPathsEnabled` may WARN (keep the
clone path short instead of changing the registry); `PYTHONUTF8` WARNs in a window opened before step 1.7.

**PyPI blocked:** install from a wheelhouse instead (§"Offline wheelhouse"), then continue with `manual status`.

### Step 4 — Hand the B1500A over from EasyEXPERT

Bring-up stage S0 ([s0-physical](../.agents/skills/b1500-bringup/stages/s0-physical.md)) in short: interlock and
shield box checked, cables recorded, EasyEXPERT reference files saved. On the B1500A: **File > Exit EasyEXPERT**
and leave the "Start EasyEXPERT" button on screen (EasyEXPERT and b1500 never control the instrument at the same
time); in the B1500A's Keysight Connection Expert set GPIB address **17** and System Controller **No**.

### Step 5 — Create the local configuration (human)

Blueprint v2 §7.5 line 6. These commands are yours alone: the harness rules and the guard hook stop a coding agent
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

### Step 6 — Probe the instrument and adopt the station

Blueprint v2 §7.5 lines 6–7; prerequisite: step 4 done (EasyEXPERT ended).

```powershell
uv run b1500 doctor
uv run b1500 doctor --probe
uv run b1500 bringup propose-station
uv run b1500 config adopt work\bringup\station.proposed.yaml --as station
uv run b1500 config check
uv run b1500 doctor --probe
```

- `doctor`: no FAIL line.
- `doctor --probe` is read-only (queries only, never `CN` or any setting command): the VISA library loads and
  `list_resources()` lists `visa.resource`; the bus opens with the exclusive lock; `*IDN?` names the B1500A
  (firmware recorded); `UNT?` against `config\local\station.yaml`; the error queue is drained; status byte; every
  output off (`LOP?`); the 16440A selector mode and outputs; `SPST?` with an SPGU installed; `CORRST?`/`ADJ?` per
  MFCMU; then unlock and close. One PASS/INFO/WARN/FAIL line each (`--json` for the full report), exit code 1 on any
  FAIL, and every raw answer in `work\bringup\probe-<UTC>.json`. The first run usually FAILs `inventory` (the
  station file is still the example) and may WARN about old errors in the queue.
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
   documentation for MCP servers that need device access and write the setting into "Recorded results" below.
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
5. **ATV-7 and ATV-11 check.** Repeat the request of step 8.5. The `run_confirmed_plan` prompt must appear in the
   default mode and show the `summary`; decline it. Fallback (ATV-7): the `requiresUserInteraction` flag (policy
   `confirmation.claude_require_user_interaction: true`, the default) forces the prompt; if no prompt appears at all,
   do not use Claude Code with the instrument and record it.

### Step 10 — Bring the instrument up with the agent

Start the harness in the clone root and give it this prompt:

> Use skill b1500-bringup and continue the hardware bring-up from the current stage.

The agent reads the stage file of the next open stage (`uv run b1500 bringup status`), tells you the physical
steps, probes and proposes, and runs validated plans only after your consent in chat; you do the physical steps,
consent in your own words and approve the harness prompt after comparing its summary with the chat. The stages and
who does what: [hardware-bringup.md](hardware-bringup.md).

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
- **Update:** close the harness, then

  ```powershell
  git pull
  uv sync --frozen
  uv run b1500 harness init --codex --check
  uv run b1500 doctor
  ```

  If the check reports drift, run `uv run b1500 harness init --codex` again (and `--claude` if used). `git pull`
  never touches `config\local\` or `data\` (both are ignored by git). After a harness upgrade repeat steps 8.2, 8.5
  and, for Claude Code, 9.4–9.5. With a wheelhouse install, a `git pull` that changes `uv.lock` needs a new
  wheelhouse first.

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

Checked on the Mac (WP6.5, commit of this document): 98 wheels (96 packages + `setuptools` + `wheel`), 81 MB, the
largest `numpy` (12.6 MB), each `cp312-win_amd64` or pure Python; the check above installed all 96 packages for
`x86_64-pc-windows-msvc`, and the clone itself built from the wheelhouse alone. The lab-PC sequence below was
rehearsed on macOS with a macOS wheelhouse: after the two `uv pip install` commands, `uv sync --frozen` with
`UV_OFFLINE=1` and an empty uv cache reported all 95 packages present and installed nothing, and `uv run` worked
offline (`doctor`, `manual status`, `pytest`).

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
manual and bring-up commands need no approval. Coding agents may never edit `.claude/settings*.json` or `.codex/**`
(both are edit-denied), so this one change set was applied once by the orchestrator at WP6.1, exactly as written
here, with the shell; the applied diff is logged in `docs/design/progress.md` (WP6.1 row).
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

Check after a `git pull` on the lab PC: `uv run b1500 harness init --codex --check` (and `--claude`) and
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

## Recorded results (fill in at deployment)

| Item | Result | Date |
|---|---|---|
| Harness versions (Codex, Claude Code, uv, Git, Python) | | |
| WGFMU instrument library version and DLL path (ATV-15) | | |
| Install route: PyPI or wheelhouse (commit it was built from) | | |
| Codex `doctor --summary` sandbox row (step 8.2) | | |
| ATV-4: server opens VISA inside Codex; setting used, if any | | |
| ATV-11: Codex approval prompt shows the summary | | |
| ATV-7: Claude Code prompts in default mode | | |
| ATV-8: Claude Code `/hooks` lists the guard hook | | |
| One-process check (bring-up L0) | | |

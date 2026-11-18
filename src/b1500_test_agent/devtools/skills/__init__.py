"""``b1500 dev lint-skills``: schema, budgets and link graph of the canonical skills (blueprint v1 6.1-6.5, v2 5.2,
6, 8.1); ``b1500 dev gen-index`` (``index``) writes the generated card index it checks.

Works on any root that has the repository layout (the repository itself or a fixture tree): skills in
``<root>/.agents/skills/``, recipes in ``<root>/recipes/`` and config in ``<root>/config/`` (both overridable), the
manual catalog in ``<root>/references/manuals/``. Every problem is one ``LintProblem`` (code, file, line, message);
the command exits 0 iff there is none. Notes (stages without a file yet, card-less recipes, citation and command
counts) never fail the run.

Checks (problem ``code`` in brackets)
-------------------------------------
- Layout [``skill_layout``]: ``.agents/skills/`` exists, holds the entry skill ``b1500-test``, every folder in it has
  a ``SKILL.md``, no symlinks inside a skill (Windows checkouts turn them into text files). Source files never carry
  the generated-copy marker [``generated_marker``] (edit sources, never paste the mirror back).
- ``SKILL.md`` frontmatter [``frontmatter``]: keys ``name`` (= folder name, lowercase-kebab, ≤64 chars) and
  ``description`` (1-300 chars), optional ``license``/``metadata``; nothing else (``allowed-tools`` would pre-approve
  tools and bypass the harness confirmation; ``hooks`` would add hooks).
- Budgets [``budget``]: entry ``SKILL.md`` ≤150 lines and ≤9,000 bytes; ``b1500-debug/SKILL.md`` ≤100 lines;
  ``b1500-bringup/SKILL.md`` ≤120 lines; cards, the card template, the generated index and stage files ≤150 lines;
  ``knowledge/**/*.md`` ≤300 lines; always-loaded text (``AGENTS.md`` + ``CLAUDE.md`` + every skill's frontmatter
  ``description``) ≤2,500 tokens, counted like ``devtools/budget.py`` (tiktoken ``o200k_base``; with the chars/3.5
  fallback an excess is only a note, because the fallback overestimates).
- Links [``link``, ``anchor``]: every relative Markdown link or image (inline or reference definition, outside code)
  in a skill file resolves, with exact case, to a file or folder inside **that** skill folder; absolute paths are
  refused; ``#anchors`` on Markdown targets (and same-file ``#anchors``) must be heading ids of the target. Heading
  ids follow GitHub: lowercase, characters other than letters, digits, ``-``, ``_`` and spaces dropped, spaces
  become ``-``, repeats get ``-1``, ``-2``; ``<a id="x">`` anchors count too.
- Knowledge files (``b1500-test/knowledge/**/*.md`` except ``README.md``) [``frontmatter``]: ``domain``,
  ``maturity`` (``seed|draft|reviewed``), ``sources`` (≥1), ``last_reviewed`` (date or null; set when reviewed).
- Test cards (``b1500-test/cards/<family>/<id>.md``; ``_*.md``, ``README.md`` and the v1 ``cards/reserved/`` folder
  are not cards) [``card_layout``]: family = folder (one of ``FAMILIES``); a card elsewhere under ``cards/`` is a
  problem. Frontmatter [``frontmatter``] = ``CardFrontmatter`` v2 (``id`` = file stem, ``title``, ``family``,
  ``intent``, ``recipes``, ``device_types``, ``modules``, ``routes``, ``bringup_stage``, ``status``,
  ``confirmation``, ``knowledge``, ``manual``, ``debug``, ``sources``, ``version``); the body has exactly the ten
  numbered H2 sections of ``CARD_SECTIONS`` in order (``## 1. Purpose and applicable devices`` ...
  ``## 10. Validation record``; ``->`` may stand for ``→``; H3 inside a section is free) [``card_sections``];
  section 2 states the routes ("Routes: none ..."), section 10 names ``validation/hw/<recipe>.yaml`` of every card
  recipe [``card_sections``]; see the section-4 contract below. ``cards/_TEMPLATE.md`` has the same ten sections.
- Card graph: card ``recipes`` exist, share the card's family, and each recipe's ``card`` points back
  [``card_recipe``]; every recipe ``card`` is an existing card in a family folder that lists the recipe, and every
  runnable recipe has a card (reserved ``not_implemented`` recipes exempt until WP11.2; ``CARDLESS_RECIPES`` by
  design) [``recipe_card``]; card ``device_types`` appear in the recipes' ``device_types`` [``card_recipe``]; card
  ``modules`` ⊆ the module types the recipes' roles may use (each role's ``module_types``, or every type that fits
  its function; ``GNDU`` when a role allows it; empty only for roleless system recipes) [``card_modules``]; card
  ``routes`` (``<switch kind>:<state>``) ⊆ the non-rest switch states whose input is a role's resource
  [``card_routes``]; ``bringup_stage`` is a blueprint 7.4 stage id, and once that stage's file exists it lists every
  card recipe [``card_stage``] (a stage without a file is a note); ``manual`` entries are canonical citations of
  catalog documents [``frontmatter``, ``citation``]; card ``knowledge`` entries ``knowledge/<file>.md#<heading-id>``
  exist [``card_knowledge``]; card ``debug`` ids are ``b1500-debug/runbooks/<id>.md`` files [``card_debug``]; every
  recipe ``analysis_defaults`` method exists in ``ANALYSIS_METHODS`` [``analysis_method``]; card ``status`` equals
  each recipe's effective status on the simulator [``card_status``].
- Card index [``card_index``] (``index``): ``cards/README.md`` equals the text ``b1500 dev gen-index`` generates from
  the card frontmatter and the registry (skipped with a note while a card's frontmatter is invalid).
- Bring-up skill [``stage``] (``stages``): ``stages/_TEMPLATE.md`` has the six numbered sections of
  ``STAGE_SECTIONS``; every other ``stages/*.md`` is named after a ``STAGES`` entry, has ``StageFrontmatter``
  (``stage`` = the file's stage, ``title``, registered non-reserved ``recipes``, ``version``) and the six sections;
  ``records/`` holds only ``_TEMPLATE.yaml``, a mapping with ``RECORD_KEYS``, empty ``reviewer`` and ``H...`` runs.
- Citations [``citation``] (``citations``): every manual citation (``PG p433 (4-115)``, legacy ``PG PDF 433``) in
  the skills, recipes, source docstrings and docs names a catalog document and a page inside it; with the committed
  corpus its printed label and quoted keyword must match the page (``references/manuals/catalog.yaml``, blueprint 5.2).
- Commands [``command``] (``commands``): every ``b1500 ...`` command named in code in the skills, stage files and
  docs (not ``docs/design/`` or the dated acceptance reports) exists in the CLI with the options named, as its
  ``--help`` shows.

Card section 4 contract ("Recipe and parameters"; for ``cards/_TEMPLATE.md`` and the cards)
--------------------------------------------------------------------------------------------
1. **Parameter table** [``param_table`` for structure, ``param_range`` for values]: a Markdown table whose first four
   header cells are ``param | default | recommended | recipe range`` (case-insensitive; further columns such as
   ``why | effect`` are free text). One row per parameter; ``param`` is the recipe parameter name (backticks
   allowed) and must belong to one of the card's recipes; ``param (recipe.id[, recipe.id])`` limits the row to
   those card recipes (for parameters whose spec differs between the card's recipes). Values: a number with an
   optional SI prefix and the parameter's unit (``-1 V``, ``50 mV``, ``1e-6``, ``1 uA``, ``100 kOhm``); intervals as
   ``low..high`` (also ``low … high``, ``low to high``, ``[low, high]``), a unitless low end takes the high end's
   unit (``20..100 mV``); ``-``, ``—``, empty or ``n/a`` mean "none" (``required`` too, for ``default``); enum values
   are choice names, lists separated by ``,``; booleans ``true``/``false``. Rules: ``default`` equals the recipe
   default (none when the recipe parameter is required) and lies inside the recipe range; ``recommended`` lies
   inside the recipe range (enum: each item is a choice); ``recipe range`` equals the recipe ``range`` (enum: the
   full choice list or none).
2. **Example plan** [``example_plan``]: exactly one fenced ```` ```yaml ```` block in section 4, a mapping with
   ``recipe_id`` (one of the card's ``recipes``), ``params`` (mapping, may be empty), ``pin_map``, ``dut_profile``
   (optional), ``sim_scenario`` (a ``config/sim/scenarios/`` name) and optional ``label``; nothing else. The lint
   validates it with ``B1500Service.validate_plan`` against a temporary copy of the config (``config/local/`` is
   never read) with ``B1500_CONFIG_DIR`` selecting ``sim_scenario`` and a temporary ``B1500_DATA_DIR``: the call must
   succeed with a tier other than ``blocked``; ``confirmation: never`` requires tier ``ok`` and
   ``confirmation: always`` tier ``needs_confirmation`` [``card_confirmation``].

Modules: ``common`` (names, schemas, stage list, report models, the ``Lint`` context), ``markdown`` (Markdown model),
``layout`` (skill folders and ``SKILL.md`` frontmatter), ``links`` (links and anchors), ``budgets`` (line, byte and
token budgets), ``params`` (card parameter tables), ``cards`` (cards, example plans, the card-recipe graph),
``index`` (generated card index, ``gen-index``), ``stages`` (bring-up skill), ``citations`` (manual citations),
``commands`` (``b1500`` commands) and ``lint`` (``lint_skills``, ``format_report``).
"""

from b1500_test_agent.devtools.skills.lint import format_report, lint_skills

__all__ = ["format_report", "lint_skills"]

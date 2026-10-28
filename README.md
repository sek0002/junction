# Junction — Golden Gate workbench

A local FastAPI app for selecting plate fragments, assembling circular plasmids, inspecting sequence checks, calculating reaction inputs, and comparing uploaded plasmids with saved and inferred designs.

## Versioning

The version beside the logo, in the footer and in API metadata comes from `app/version.py`. Each published update increments it once: **patch** for fixes and small interface changes, **minor** for new features, and **major** for breaking changes. Start a release with `python3 scripts/bump_version.py patch` (or `minor` / `major`); minor and major increments reset the lower numbers. The version persists across restarts and deployments, and does not change just because the server starts.

## Start

On macOS, double-click **start.command**, or run:

```sh
./start.command
```

Open **http://127.0.0.1:8765**. The launcher uses an available Python with dependencies, or creates a local `.venv` and installs `requirements.txt`. Python 3.10 or later is required. A conventional setup also works:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Set `GOLDEN_GATE_PORT` for a different port. Set `GOLDEN_GATE_DB` to place the persistent database elsewhere. The default database is `data/golden_gate.sqlite3`; keep that file to preserve imports, measured stock concentrations, and saved plasmids. Restarting does not reset it. The app binds to localhost by default (`GOLDEN_GATE_HOST` can override the bind address) and has no external telemetry, AI/API dependency, CDN, or external account.


## Home server

For Linux/systemd installation, a persistent random port, updates and backups, see [DEPLOYMENT.md](DEPLOYMENT.md). The service keeps its database under `/var/lib/junction`, separately from the repository.

## Login and accounts

A fresh database creates username **admin** with a unique random 12-digit PIN. Read it from `data/golden_gate.initial-admin-pin` (or the `.initial-admin-pin` file next to a custom database), then sign in. This private file is created with owner-only permissions and excluded from Git. The account is created once in each new database. Restarting never resets a changed PIN or existing users. The header profile icon opens **Change PIN**, **Sign out**, and (for admins) **Users**. Hover the icon to see the signed-in username. PINs contain 6–12 digits; leading zeros are preserved. At least one active admin must remain.

All users share uploaded plates, fragments, saved plasmids, stock records and default inventory rules. Each user has a private, persistent **sandbox**: the current assembly draft, nested inserts, Build list, reaction settings, stock overrides, planner/import preferences and comparison files/results. These are stored in SQLite and restored after sign-out, refresh, server restart or sign-in on another device. A saved assembly explicitly added to the plasmid library becomes shared. Comparison references include shared plasmids and recipes plus only the current user's Build list. Upgrading assigns legacy Build list entries to the original admin. Old unscoped browser planner preferences are not imported into other users' sandboxes.

Admins can create users, change roles, reset PINs, disable/enable accounts, or **Delete** them. Deletion revokes sessions and hides the account; its sandbox and history are retained. **Show deleted → Restore** recovers the account in a disabled state; enable it to permit sign-in. Usernames remain reserved for recovery. Admins cannot delete themselves or remove the last active admin.

Per-user library permissions control **Uploads** (including saving assemblies into the shared library), **Edit library** (fragment stocks, plasmid names/topology/templates and applying/resetting stock rules), **Archive** (archive/restore shared records), and **Default rules**. Admins always have full access. Every account can read and export the shared library and edit its own sandbox even with all library permissions disabled. Restrictions are checked server-side on every request and apply to existing sessions immediately; restricted controls are disabled in the UI. A tab also sends its account identity, so switching accounts in another tab cannot silently write the old sandbox into the new account.

**Users → Activity**, or a user's Activity button, shows dated sign-ins, account changes, uploads, library changes, builds, comparisons and downloads with HTTP outcomes. Filter by user and load older entries. Activity is persistent and admin-only; it records operation paths/IDs and outcomes, without PINs, session tokens, request bodies or sequence contents. Draft autosaves are kept in the sandbox without adding an activity row for each keystroke.

Accounts and sessions live in the same SQLite database as inventory. PINs use salted scrypt hashes; sessions use random tokens with only their hashes stored server-side. HttpOnly, SameSite=Strict cookies keep a login for seven days, including refreshes and server restarts. HTTPS cookies are marked Secure. Changing or resetting a PIN invalidates all sessions for that user; disabling an account also revokes its sessions. Sign out invalidates the current session. Failed sign-in attempts are limited per username (five) and client IP (twenty) within fifteen minutes, with counters persisted across restarts. APIs, downloads, app HTML and API docs require a valid session; static branding and the login page remain public. API and app responses are not cached. Browser writes reject cross-origin requests.

Use **Change PIN** to replace the initial admin PIN before exposing a deployment beyond localhost. API clients sign in with `POST /api/auth/login` and retain the returned session cookie. The initial credential is never displayed on the login page, returned by an API or written to logs. Changing or resetting the original admin PIN removes the bootstrap file. For unattended installation, a private `GOLDEN_GATE_INITIAL_ADMIN_PIN` environment value may supply a 6–12 digit initial PIN; it affects only a fresh database. Existing accounts and PINs are never reset during an upgrade.


## Install on mobile or desktop

Junction includes a web-app manifest, install icons, a root-scoped service worker and an **Install Junction** icon in the top bar. Supported browsers can add it to a home screen or launch it in its own window. On iPhone/iPad, open the site in Safari, then choose **Share → Add to Home Screen → Open as Web App**. Chrome/Edge use the browser's Install action; the app button opens the native prompt when available and shows instructions otherwise.

A phone or tablet must open a **reachable HTTPS URL** for the server. `http://127.0.0.1:8765` is a development exception on the computer running Junction; a phone's localhost points to the phone. Deploy the FastAPI server behind your HTTPS hosting service or a private HTTPS reverse proxy. For an existing reverse proxy on another host, bind explicitly with `GOLDEN_GATE_HOST=0.0.0.0 ./start.command`; the default remains local. Keep `data/golden_gate.sqlite3` on persistent storage and protect access through the hosting service; Junction requires its built-in user login.

Installation does not copy the database to the device. All clients connect to the same server for inventory, calculations, uploads and exports. The service worker caches only public static assets and an offline screen. API requests are network-only, failed writes are not queued, and an offline navigation shows a reconnect screen. The installed app needs the server to remain running. No automatic reload interrupts an open assembly.

The header and favicon use the transparent SVG master with a modular J silhouette, with 192/512-pixel home-screen icons and a separate maskable icon for platforms that need a solid safe-area tile. A transparent 4096×4096 PNG is included at `app/static/assets/junction-mark-v4-4096.png`.

Use **Dark mode** in the header to switch appearance. The app follows the system theme until a choice is saved in the browser. Printed tables remain light.

Fresh installs start with the current eight Twist plate maps (218 fragments) listed in `data/golden_gate.sources.json`, with original CSV/XLSX files included in `data/inventory_sources/`. The same bundled manifest is used for a fresh database at another path. A per-database `.sources.json` manifest takes precedence, including explicitly empty source lists. Imports are idempotent: restarts preserve edited stocks and archived records. The withdrawn `pSHPs0309B323501IQ` plate is excluded from the bundle and archived once when an existing database is upgraded. The archive can restore it explicitly; restarts do not undo that choice. Three circular backbone examples are seeded separately: pIVT_V2, pULT_V2, and pHR_V2.

## Twist Platemaps

Uploads → **Twist Platemaps** starts with these eight stored maps, with plate viewers and CSV exports:

- `platemap_pSHPs0314B2111016N_.csv`: 23 fragments.
- `platemap_pSHPs0405B231201IQ_.csv`: 22 fragments.
- `platemap_pSHPs0622B228801IQ_.xlsx`: 34 fragments.
- `platemap_pSHPs0711B5402016N_.xlsx`: 22 fragments (Strict OOXML supported).
- `platemap_pSHPs0726B1170017B_.csv`: 15 fragments in two tables: 0726 (4) and 0702 (11).
- `platemap_pSHPs0921B1498017B.xlsx`: 96 fragments.
- `platemap_pSHPs0921B1498027B.xlsx`: 6 fragments.

There are 218 unique plate/well records across eight plates, supplied in seven files. Original sequences, yields, identifiers and well locations are retained. Planned concentrations are calculated from the library rules and are not labelled as measured stocks. The two original plate maps and older GenBank references in `examples/` remain available as regression/reference files; the bundled eight-plate manifest controls the initial inventory.

The five supplied precalculated files cover 173 fragments on six plates. Their source concentrations, yields and independently verified resuspension volumes are stored as the initial defaults. Verification uses physical construct length, 660 g/mol/bp, 0.05 pmol per fragment and a 1:1 ratio: target mass = bp × 660 × 0.05 / 1000, resuspension = yield / stock, and use = target mass / stock. All 173 source rows agree. Forty-two rows exceed the current resuspension or aliquot limits; the requested values are retained and warnings stay visible. These are saved plans, not measured concentrations.

The seed manifest's `precalculated_plate_files` list is restricted to its `plate_files`. First import upgrades matching existing DNA without changing IDs or fragment sequences. Identical source files are idempotent: startup does not overwrite later stock edits or restore archives. **Set Default** and each row's reset restore these source defaults. Other initial plates and future uploads use the normal rules. Source-only `Conc (ng/uL)` and `H2O` fields do not silently override the rules for ordinary uploads; explicit canonical stock/resuspension fields remain supported. CSV files may contain repeated headers with different column orders and multiple plate IDs.

The builder search provides plasmid recipes for pIVT, pULT, and two pHR variants using the four-part F21 split. Type **Plasmid** to list the presets, optionally followed by a name; select one to load its full assembly. Presets stay hidden unless the search includes the word Plasmid. AAV6 is shown as unavailable because F12 is absent from the delivered maps. Actual delivered sequences produce a 2,827-bp pIVT (the vendor F10 differs from the earlier 2,937-bp design), 7,457-bp pULT BsaI-ve, 7,760-bp pHR BsaI-ve, and 8,201-bp pHR U6. Recipe checks always use the inventory, rather than substituting an old reference.

The **GenBank** icon in the assembly viewer downloads the displayed assembly with its current name, topology and annotations. The download icon in the **Build list** exports every queued product as a separate GenBank file in a dated ZIP with a unique build-list identifier. Removed entries and other users' builds are excluded. Queued designs are rebuilt against current inventory; an invalid or unavailable entry blocks the ZIP rather than being silently omitted. Reaction-volume warnings do not block sequence downloads. The **+** beside the fragment chain still adds an independent assembly to the list.

## Design

**Design** creates new synthesis fragments without changing the shared library or the current Assembly draft. Designs autosave in the signed-in user's private sandbox; the saved-design selector keeps separate designs across refreshes and sign-ins.

1. View icons on backbone and fragment/insert cards open the interactive map and base viewer. Insert previews show the current orientation, Constant/Dynamic regions and detected restriction sites. These previews are read-only; Back, Escape or clicking outside returns to the unchanged design.
2. Select an installed backbone and cassette, or start without a backbone. Reference cards show BsaI, BsmBI and mixed-enzyme cassettes with their required four-base ends. Search existing fragments by name; compatible donor orientation is detected automatically from backbone/neighbor overhangs, drag cards to reorder, or use Alt+Left/Right on a card. Use **+ Placeholder** or the small plus between cards to position an insert.
3. Paste a placeholder's full insert payload in DNA or FASTA format. Neighboring fragments and the selected backbone supply its external fusion labels. When an unconnected end has no specified label, the insert's terminal four bases become that end; explicit open-end labels can be entered in Options. The quick scan lists the common Type II panel: BsaI, BsmBI, BbsI, HindIII, EcoRI, BamHI, XbaI, NotI, XhoI, PstI, EcoRV, KpnI, NheI, SpeI, SalI and SapI. This is a named panel, not an exhaustive restriction-enzyme database. Active assembly-enzyme sites block generation. Other panel enzymes are informational unless selected under site exclusions.
4. Drag across the rendered bases, then add a named **Constant** or **Dynamic** region. Start/end fields provide the same operation for keyboard and touch use. Coordinates are one-based and inclusive in the UI. New insert DNA and its regions stay exactly as entered: naked payloads have no overhangs from which to infer a biological orientation. Existing donor blocks use the compatible orientation with the fewest reversals; unresolved/mismatched overhangs still fail QC. An RC badge reports an automatically reversed library donor. Previously edited insert DNA is retained as saved. Regions appear in sequence order; unmarked sequence is Constant. Each Dynamic region accepts pasted FASTA alternatives. Each record replaces only that region, preserving the other DNA and its assembly position. Constant regions have no alternatives.
5. **Generate fragments** finds native four-base junctions near section boundaries. The boundary window defaults to ±20 nt; zero requires exact boundaries. Shared overlaps are counted once and the original assembled DNA is preserved. Dynamic boundaries move outward into constant flanks so all variants use identical ends; adjacent Dynamic regions without suitable constant junctions are rejected. New internal labels cannot be palindromic or duplicate/reverse-complement any selected assembly label or supplied exclusion. Fixed problematic labels are reported by the existing assembly validator. The app does not mutate recognition sites or add arbitrary junction scars.
6. The **Variant table** has one Name column, read-only Constant columns and one input per Dynamic region, in sequence order. Paste TSV from a spreadsheet directly into a Name or Dynamic cell, or use **Paste rows** for CSV/TSV. Compact input uses Name followed by Dynamic sequences; a full copied table also works if every Constant is unchanged. **Reference row** fills all Dynamic inputs from the template. **Use rows** pairs the inputs on each row into one named assembly, replacing independent FASTA alternatives. Missing, invalid, duplicate-name or obsolete-region inputs block export. Constants are generated once and shared; every row's overhangs, donor digestion and final assembly are checked.
7. Choose **5′ RE** and **3′ RE** independently, or keep Auto to follow the assembly enzyme. Both BsaI and BsmBI ends are supported; mixed ends require the dual-enzyme reaction. **Add RE sites** includes six external clamp bases, the recognition site, a spacer and the four-base overhang at each end of the exported full sequence. Turning it off exports overhang + target + overhang; digestion checks still validate the selected adapter design. The target sequence excludes adapters and fusion labels. Its reference coordinates can include constant flanks around a shorter or longer Dynamic replacement; the exported target and full lengths describe the actual variant.
8. Use **Example GenBank** to review one annotated reference assembly before mass generation. It uses the full reference insert DNA, includes Constant/Dynamic region annotations and fusion features, and ignores the variant table and FASTA alternatives. The design and table stay unchanged. Backbone/fragment compatibility and reference-sequence checks still apply. **RC output** changes only the exported strand representation. Target/full donor sequences, overhangs, end enzymes and end sequences are reversed together; CSV/Excel include an orientation column. Assembly CSV and GenBank use the reverse-complement molecule, with GenBank features remapped to the opposite strand. Reference coordinate columns remain coordinates in the original design. RC FASTA headers and filenames are marked. Previews, region coordinates, variant inputs and assembly checks are unaffected; the export choice autosaves with the design.
9. Review lengths, GC, fusion labels, boundary shifts and ordered assembly previews. **Fragments CSV** and **Excel** include target and full sequences, end sequences, overhangs, enzymes, region, assembly row and reference coordinates. Excel has Fragments, Assemblies and Overhangs sheets. **FASTA · Full** and **FASTA · Targets** export the corresponding donor sequences; **Assemblies CSV** and **GenBank** contain every checked full assembly. Independent FASTA mode includes the reference and all combinations; table mode includes exactly the named rows. Exports are blocked on design errors. Recognition sites are never silently removed or mutated.

The Generate preview is interactive: hover or focus features and restriction sites for details, click a feature to select it, switch circular/linear views, or open the full sequence viewer with the view icon. Labels use the same separated rows/columns and leader lines as the Assembly viewer. The preview has its own record and does not replace the assembly draft. Table designs identify the first displayed row in the viewer name.

**Make Twist Compatible** is off by default and saved with each design. When enabled, generated full fragments shorter than 300 bp receive 3′ padding to exactly 300 bp; fragments already at least 300 bp are unchanged. The pseudorandom tail is reproducible for the same fragment, uses the closest feasible integer to 50% GC (40–60% GC in every 50-base padding window), and adds no sites from the common Type II panel or runs of five identical bases, including across the junction. Existing fragment DNA and intentional adapter sites are preserved. Padding is outside the 3′ adapter when **Add RE sites** is on. CSV/Excel include separate unpadded-sequence and padding columns; Full FASTA includes the padding. Target FASTA, target sequences and assembled products remain unchanged. This option implements the 300-bp minimum and padding checks; it does not certify every Twist synthesis criterion.

Generation supports up to 100 ordered inputs, 100 highlighted regions and 150,000 template/independent-variant bases per design. Independent FASTA mode allows eight alternatives per Dynamic region and 64 combinations. Table mode supports 384 named rows with one million pasted input bases. All products together are bounded at two million assembled bases. Templates must pass the selected enzyme/site checks before row replacements. Excel rejects sequences over its 32,767-character cell limit; CSV and FASTA preserve longer sequences. A design that cannot meet its fixed context or these limits reports the cause. Exact and reverse-complement conflicts are checked; empirical mismatch-ligation fidelity is not predicted. Recognition conventions and adapter geometry follow [NEB's recognition-specificity reference](https://www.neb.com/en-us/tools-and-resources/selection-charts/alphabetized-list-of-recognition-specificities) and [Golden Gate insert guidance](https://www.neb.com/en/tools-and-resources/usage-guidelines/insert-considerations-when-using-neb-golden-gate-assembly-kit-bsai-hfv2-neb-e1601).

## Assembly builder

Palindromic four-base overhangs (equal to their reverse complement, e.g. TCGA or ATAT) are flagged in yellow throughout the UI, including backbone linkers, cassette selectors, nested assemblies, fragment searches, plate details, previews and QC messages. Hover shows the self-ligation warning. Sequence views flag annotated palindromic fusion positions; ordinary matching DNA words are not flagged. Plate wells with palindromic overhangs have a yellow indicator. Yellow takes precedence over other linker colors; existing validation rules are unchanged. Spreadsheet downloads also flag explicit palindromic fusion-label cells in yellow.

1. Select BsaI, BsmBI or the dual-enzyme mode. Backbone selection keeps your chosen enzyme; change it manually when another cassette is needed. Choose **No backbone** to assemble an ordered fragment chain, or select one of the three example plasmids (or another saved circular plasmid) and its outward-facing insertion cassette. Uploaded plate fragments never appear in the backbone selector. Add F1 as an ordinary fragment when a first-round recipe requires it.
2. Search fragments by name, or search **Plasmid** (optionally followed by a name) for complete assembly presets. Presets appear only when the query includes the word Plasmid, regardless of the current enzyme or compatible-end filter. Search tolerates partial names and approximate spelling for longer queries; plate IDs and wells remain visible as location information. The plate dropdown filters the library separately. Compatible-end filtering and visible fusion labels guide selection; it never silently substitutes a fragment. Selected fragments form compact tiles with four-base joiners; purple joiners mark the backbone ends. Click a tile for alternatives: empty ends and unmatched backbone ends can change, while occupied fragment junctions and already matched backbone ends stay constrained. A fragment connected on both sides therefore shows only compatible swaps. Backbone repairs rank first; options that leave a backbone mismatch are labelled. Use the red hover/focus × to remove a fragment, or drag tiles to reorder. Swapping reruns the assembly checks.
3. Topology is detected as fragments are selected. A valid ordered chain whose last overhang matches its first overhang is circular; otherwise it remains linear. Every change automatically checks the ordered assembly, including open chains and incompatible junctions. The Assembly card reports **Pass** or **Fail**; each fragment shows a green tick or red exclamation mark with digest, overhang and restriction-site details on hover or keyboard focus. Reaction-volume readiness remains separate in the planner. Donor outer enzyme adapters, external synthesis adapters, and external buffers are removed. A shared four-base fusion sequence is retained once. GenBank exports and saved sequences retain the detected topology.
4. Review active-enzyme cuts, mismatched ends, palindromic and repeated/reverse-complement fusion labels, retained other-enzyme cassettes, and round-two conflicts. Invalid products cannot be saved or exported as valid GenBank assemblies. A diagnostic worksheet remains available and is explicitly marked when blocked.
5. Inspect the circular/linear map, select a feature, navigate the base sequence, download an annotated GenBank, or save the product as another reference. **Save backbone** is enabled for valid circular assemblies with a usable BsaI or BsmBI replacement cassette. Saved templates persist under **Saved backbones** in the backbone selector, labelled with the enzyme for the next round. Switch to that enzyme and select its cassette to assemble the next insert. Saving an existing exact product as a backbone promotes it without creating a duplicate. Single recognition sites, linear products, and unpaired active cuts do not qualify. Multiple complete cassettes are allowed as templates; every cassette opened by the selected enzymes needs compatible inserts, and assembly QC still flags unresolved cuts.

Selecting one cassette on a plasmid with additional active-enzyme sites is blocked: those other sites will also cut. Simultaneous replacement of multiple backbone cassettes is not yet supported. Single-cassette designs and multi-fragment insert chains are supported. Other-enzyme sites can be deliberately retained; the app does not mutate them.

Click the plasmid name above the viewer map to rename it. Changes autosave after a short pause, on Enter, or when leaving the field. Stored plasmids keep the same record ID, DNA sequence, annotations, and template settings; renamed example backbones are retained across restarts. Draft names update the current assembly and exports. Renaming a loaded build creates a separate draft; use **+** to add it as a new entry.

## Build list

Use **+** beneath Fragments to add an independent snapshot of the current assembly to the integrated **Build list**. The current name, fragments, backbone, nested inserts and reaction settings stay in the builder, so you can change a variant and add it without starting fresh. Select an entry to load its setup; changing its name, fragments, backbone, cassette or enzyme creates a separate draft and preserves the original entry. Reaction settings still autosave to a selected entry while its design is unchanged, and Build plans remains editable per row. Hover or focus an entry for its ordered inputs, overhangs and plate locations. The document icon explicitly clears the builder for a fresh assembly. Loading an example starts a separate draft. Every **+** adds a new entry; duplicate names receive a numbered suffix in the list. Queued requests persist in SQLite and keep their own rules, instance stock overrides and manual backbone concentration. **Build plans** compares reaction volumes, and **Spreadsheet** exports queued plans. Missing or archived inputs are flagged. **×** removes a build with **Undo remove** available across reloads. The list supports up to 50 active entries.

## Concentrations and printable reference sheets

The builder has **Build**, **Reaction planner** and **Export assemblies** tabs. The default plan uses **0.05 pmol backbone**, a **1:1** insert-to-backbone ratio, **1–5 µL per fragment input**, and **less than 100 µL resuspension per fragment**. Backbone stock is entered in a separate calculator: volume = input pmol × backbone bp × 660 / 1000 / stock ng/µL. When no entered or saved backbone stock is available, use **1 µL** and keep the stock concentration unknown. This default is included in water calculations and exports; supplying a stock restores the calculated volume. Fragment resuspension and aliquot limits do not apply to the backbone. In **No backbone** mode, each fragment receives 0.05 pmol without using any fragment as a backbone reference. Legacy API calls can still request an explicit fragment reference; the app selector uses only whole plasmids.

Click the **Inputs** or **Resuspension** rule card in the reaction planner to edit its limits. DNA amount, insert ratio, total volume, and other reagents can be edited directly. Planner overrides are remembered in this browser and included in exports without changing the library default rules or recorded fragment stocks. Each rule card has a Reset action.

Calculations use 660 g/mol/bp for dsDNA:

- Resuspension µL = delivered yield ng / target stock ng/µL.
- fmol = mass ng × 1,000,000 / (physical DNA bp × 660).
- Default required mass ng = 50 fmol × physical DNA bp × 660 / 1,000,000.
- Feasible resuspension µL lies between yield / required ng and 5 × yield / required ng, subject to the 99.99-µL cap.
- Resuspension prefers 50 µL, then adjusts to the feasible interval at 0.01-µL precision. The lower bound rounds upward and upper bound downward so rounding preserves the input limits.
- Stock nM = stock ng/µL × 1,000,000 / (physical DNA bp × 660).
- Required insert mass follows the molar ratio; µL to pipette = required ng / stock ng/µL.

**Physical input length includes vendor synthesis adapters and buffers** when a full Construct Sequence is supplied. The shorter digested payload length is not used to infer the amount of the stock molecule. Circular plasmid length is used for a plasmid backbone.

Insufficient yield, a resuspension lower bound above the cap, or missing required data produces an unavailable plan with a reason. The app never fabricates a concentration to make an infeasible row pass. Legacy **1 µL** and **Fixed stock** modes remain available through the API and workbook settings. Neither mode writes a planned concentration into the measured stock fields.

Unknown stocks stay unavailable for pipetting unless **Use planned stocks** is enabled. The default uses each fragment's proposed concentration; Fixed stock uses the common target. Enter measured stocks in the fragment library. A measured/entered stock always overrides the proposal, and the planner flags actual inputs outside 1–5 µL. Missing stocks, original yield limits, and overfilled reactions are surfaced. Master mix input should include all enzymes/buffer and non-DNA reagents except water; the app does not prescribe a reaction protocol.

Download the inventory resuspension worksheet or an assembly-specific workbook. They contain plate IDs, wells, delivered mass, full input bp, target concentration, resuspension volume, recorded stock/resuspension fields, required fmol/ng, µL to pipette, water, and explicit checks. Assembly and build-list exports use compact A4 portrait tables with transfers side by side, repeated headers and one-page-wide Excel print settings. Explanatory paragraphs are omitted; titles, column labels and actionable checks remain. Inventory worksheets retain their existing landscape layouts. The **Resuspension plan** sheet is a computed export snapshot for immediate printing. **Resuspension inventory** and **Assembly pipetting** recalculate editable formulas in Excel. Settings B8 is reference bp, B11 is mode, B12 is the legacy fixed input, B13:B17 contain the molar dose, preferred resuspension, cap, and input limits, and B18 indicates a fragment-only plan. Generate current reference workbooks and CSVs from the app using the active inventory and your chosen rules. For F1's 1,808-bp physical molecule, 0.05 pmol is 59.664 ng.

## Uploads

The separate Uploads view accepts CSV/TSV/XLSX plate maps and GenBank/FASTA plasmids. Plate maps can be previewed before import, with per-fragment resuspension proposals calculated from the selected backbone reference and the current resuspension rules. Expected plate headers follow the example files: `Name`, `Plate ID`, `Well Location`, `Insert Sequence`, `Construct Sequence (Insert + Adapters)`, and `Yield (ng)`. Optional `Stock ng/uL`, `Resuspension uL`, and `Notes` columns are accepted. Names, plate/well keys, alphabets, supplied lengths, and insert containment are validated. Importing the same file does not duplicate records. A conflicting occupied well rejects the entire import; rename the plate ID for a genuinely new physical plate. Upload contents are data, never executable instructions.

GenBank retains supported feature types, qualifiers, strand, and compound locations. Imported FASTA records are linear references unless circular topology is supplied via GenBank. Upload limit: 10 MB. Stored plasmid limit: 100,000 nt. Comparison limit: 30,000 nt per query.

## Plate maps

**Twist Platemaps** lists the stored inventory plates, including newly imported maps. Check individual plates or Select all, then use the red archive icon to hide their fragments from searches, assembly, comparison inference and inventory plans. Archive holds a restorable plate entry; stock values, sequences, and individual fragment archive states are preserved. Restoring a plate does not restore fragments that were individually archived. Repeated default seeding never restores archived plates. Restore a plate before importing additional wells into it.

Click a plate to open its well layout. Wells beyond H12 select a 384-well layout (A–P, 1–24); otherwise the view defaults to 96 wells (A–H, 1–12). Sparse 384-well maps can fit the smaller bounds, so Layout can be switched to 384 manually. Occupied wells show labels and support hover/focus previews; click or use arrow keys for details including plate, well, fragment, overhangs, restriction sites, yield, stock and resuspension/reaction volumes. Labels can be hidden. Archived wells are dimmed. The viewer automatically detects BsaI, BsmBI, BbsI, and HindIII per well, independently of the builder enzyme. It shows each recognition site and four-base overhang with orientation and 1-based fragment coordinates; uniquely mapped constructs also show construct coordinates. Terminal adapters and internal sites are identified without enzyme QC verdicts. Stock details remain available in an expandable section. Plate downloads export stored records as CSV, including an archive flag.

## Plasmid comparison

Compare accepts multiple GenBank/FASTA files, folder selection, and dropped files or folders (including subfolders). Files are listed immediately and compared automatically, one file at a time; more files can be added during or after comparison. Duplicate paths with the same size and modification time are skipped. Unsupported files are listed as skipped. Submitted comparison files and results are saved in the user's private sandbox, separately from the shared library; refresh restores them. Removing files or clearing the list hides that user's saved comparisons. Unsupported or unsubmitted files remain temporary. Up to 200 files may be queued, with 10 MiB per file, 100 records per file and 30,000 nt per record. Multi-record files have individual record tabs; a record-level error does not block the remaining records.

Search **Files** by filename, sample, matched plasmid or fragment name. The filter selects exact matches, differences, no matches, processing status or selected files. Click File, Status, Closest match, Identity or Fragments to sort; click again to reverse the order. Filtering and sorting do not change comparison processing order or detach expanded details. Select-all affects only visible completed files. Hidden selections remain selected and are included in **Selected** exports; **100% matches** exports still include all exact results.

Table column headers across the app support ascending/descending sorting, including reaction plans, resuspension, exports, annotations and Archive. Numeric values sort numerically, names and wells use natural order, and unknown values stay last. Sorting keeps editable fields and row selections intact.

**Auto detect** tests BsaI, BsmBI, and dual-enzyme fragment assembly paths. Final plasmids can have no original recognition sites, so retained sites are reported separately from compatible assembly paths. Multiple compatible paths remain ambiguous; the app does not claim to know the historical enzyme. Changing the selector automatically reruns the queue.

The search considers saved plasmids, valid assemblies in the Build list, available assembly recipes, and candidate circles found by an evidence-guided overhang graph of the fragment inventory. It also reconstructs insert assemblies inside usable cassettes of the available circular backbone references, testing both donor orientations and comparing the entire retained backbone plus insert chain. Routes use at most one backbone cassette; unresolved extra active-enzyme cuts are excluded. Identical references (including circular rotations and opposite strands) share a result with source aliases and preserve their assembly routes under **Assembly fragments** in the alignment popup. Fragment-graph inference excludes donors with extra sites for the selected enzyme and returns up to 64 candidates per mode with bounded start/beam/depth; Search details discloses its coverage. It is not an exhaustive combinatorial search, and an inferred closest match is not proof of cloning history.

Use the circular-arrow **Recompare** icon on a completed file to update its saved result after library or application changes. Exact insert-fragment matches do not imply an exact whole-plasmid match when the backbone differs.

Fragment matches are also searched directly, independently of whole-plasmid inference. Exact full-input and digested-payload matches are tested on both strands, including a circular origin when circular context is available. A bounded anchor-guided shortlist (60 variant orientations) reports approximate matches, coverage and substitutions/deletions/insertions. Shared or short matches can overlap and do not identify a unique source fragment. Unreported fragments are not proven absent. Fragment difference coordinates follow the matched strand, with uploaded-query spans shown separately.

Candidates are shortlisted by shared sequence, then aligned in both orientations with circular rotations. The viewer reports substitutions, insertions, and missing reference segments; highlights aligned differences; and lists coordinates. Reference and oriented-query coordinates are 1-based in the UI. Original-query spans are provided when orientation/rotation differs. Internally, all feature and alignment coordinates are zero-based, half-open.

The alignment is an anchored pairwise implementation with dynamic programming for small gaps, not a clinical variant caller or exhaustive large-rearrangement aligner. Exact rotations/reverse complements, SNPs, insertions, and a 941-bp deletion are covered by tests. Large/complex unanchored regions include a limitation notice in the result. Donor compatibility, gene identity, protein function, and experimental ligation fidelity are not inferred from an exact DNA match.

## Tests and API

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
node --test tests/test_overhangs.cjs tests/test_compare_queue.cjs tests/test_map_layout.cjs
```

Use the environment containing the requirements, e.g. `.venv/bin/python`. Tests cover cut geometry, circular boundary sites, backbone digestion, overhang collisions, internal-site rejection, GenBank roundtrips, concentration arithmetic, unknown inputs, printable workbook formulas, import transactions, persistence, recipes from the actual plates, and alignment differences.

Interactive API docs are at `/docs`. Primary endpoints: `/api/fragments`, `/api/plasmids`, `/api/assemblies/preview`, `/api/assemblies`, `/api/assemblies/genbank`, `/api/assemblies/worksheet`, `/api/inventory/resuspension`, `/api/inventory/worksheet`, `/api/uploads/plate`, `/api/uploads/plasmid`, `/api/compare`.

## Plasmid topology and templates

Plasmid uploads offer **From file**, **Circular**, and **Linear** topology. Check **Backbone template** to import a circular backbone with complete BsaI, BsmBI or dual-cut replacement cassettes. Multiple cassettes are supported. This applies to every record in the uploaded file; all records are validated before import. FASTA remains linear with **From file**, so select Circular when importing a known circular plasmid.

After upload, change **Topology** and **Backbone template** under **Plasmids** on either Uploads or Fragments, then select **Save**. Setting a plasmid to Linear clears its backbone-template designation. Sequence, annotations, recipe, and measured stock information are preserved; GenBank exports use the saved topology. Explicit topology overrides also update an existing matching upload without creating a duplicate.

## Inventory editing, sorting and Bin

The fragment library fills **Stock ng/µL** and **Resuspend µL** from the saved planning rules and current yield. Unsaved defaults are labelled **Planned**; infeasible rows stay blank with a reason. The **Rules** editor saves molar input, fragment ratio, preferred/capped resuspension and aliquot limits to SQLite. Defaults remain 0.05 pmol, 1:1, 50 µL preferred, 99.99 µL cap and 1–5 µL aliquots. Rules accept any positive finite value, without fixed volume, ratio or molar-input ceilings; minimum aliquot must not exceed maximum. Saving rules persists them in SQLite across restarts. Rule changes update planned rows and leave saved stock records intact. Assembly planning and spreadsheet exports use the edited rules.

Each yield field has a lock button. **Locked** keeps yield fixed and read-only: editing stock recalculates volume, and editing volume recalculates stock. **Unlocked** allows yield editing and calculates yield = stock × volume when either stock or volume changes. Edits autosave after a short pause or when leaving a field; row status shows Saving, Saved or a save error. Locks persist without turning an unmeasured default stock into a recorded stock. Pending edits are serialized per row so newer edits win. Calculated and entered quantities are not labelled as experimentally measured. Unsaved edits survive sorting and filtering. **The circular-arrow icon** restores one fragment's uploaded yield, default calculation and locked state. **Set Default** resets only checked fragment rows and is disabled when none are selected. Reset waits for in-flight autosaves so an older edit cannot overwrite the defaults. **Reset rules** restores the original planning rules separately. Original yields are retained in an immutable reset field. Existing databases capture their current supplied yields during the first migration; new uploads retain their supplied yields at import.

**Well** is separate from Plate. Click a column heading to sort ascending, then descending. Names and wells sort naturally (A2 before A10); numeric columns use numbers and unknown values stay last. Fusion labels explicitly identify the submitted strand's **5′ end** and **3′ end**, rather than using arrows. These labels describe sequence boundaries, not different sticky-end polarities.

Checkboxes select individual fragments or all currently filtered fragments. Click plasmid cards, drag a selection box, or use the select-all icon to select plasmids. **The red bin icon** moves selected records to **Bin** and removes them from active search, planning and backbone choices. **Restore selected** brings them back with their original IDs, sequences, annotations, recipes and saved quantities. Startup imports do not resurrect archived plate fragments or bundled examples. There is no permanent-delete action. A database backup was taken before migrating the live inventory.

Reaction planner stock modes: **Use saved stocks** uses each fragment’s saved or default library concentration. Uncheck it to generate new concentrations from the separate **Custom resuspension** target and rules. Reaction input, ratio, total volume, other reagents and manual backbone stock remain editable in either mode. The resuspension table supports linked yield/stock/volume edits, yield locks and row/table reset. These instance values apply to the current reaction, queued design and worksheet exports, without changing fragment inventory. Changing stock mode clears local table edits.

The Assembly, Fragments and Compare enzyme selectors also support **BsmBI + BsaI**. Both recognition-site families are active in this mode. Donors may have BsaI, BsmBI or mixed outer adapters; compatible four-base fusion labels still have to match. Retained sites for either enzyme, including sites created at junctions or across a circular origin, fail validation. Internal cassettes are not preserved for a second round when both enzymes are selected. Each input must yield one unambiguous retained donor or backbone; extra active cuts are reported instead of silently choosing one of several digestion products.

The Assembly card’s **Build list QC** indicator summarizes sequence checks for queued assemblies only. Unqueued drafts retain fragment checks and QC details but do not affect this overall status. The build list sits below the QC details.

Cassette options identify the actual boundary enzymes: **BsaI cassette**, **BsmBI cassette**, or **Dual cut cassette** for mixed boundaries. Selecting the dual reaction mode does not relabel a same-enzyme cassette as dual cut.

Backbone dropdown options flag detected **[BsmBI]** and **[BsaI]** recognition sites, independently of the selected reaction enzyme. Both flags appear when both enzymes are detected; **[No GG sites]** marks neither. Hover text gives site counts. Cassette validation still determines whether the sites form a usable replacement cassette.


### Nested assemblies

Selected fragments with internal outward-facing BsaI/BsmBI cassette pairs show a compact bracket graphic and nested-fragment count inside the parent card. Hover or focus the indicator for ordered donor names, plate/well locations, cassette ends, reaction mode, and live validation. Click it to expand or collapse the search editor below the fragment chain. Empty cassettes remain selectable. Cassette ends and enzyme labels come from the sequence.

- **Together** cuts the original parent and nested donors in the main reaction. Choose an enzyme selection that cuts both outer adapters and nested cassette boundaries. All active internal sites and competing overhangs are checked.
- **Separate first** plans a separate cassette replacement, followed by the main assembly using the prepared parent. Enter the measured prepared-parent stock; the original inventory concentration is not reused. The stage amount covers the main input at theoretical complete recovery, so actual preparation must allow for assembly and purification losses.

Nested selections persist with the build list and saved plasmid recipes. Viewer and GenBank features include nested donors. Assembly and build-list spreadsheets include nested recipes, separate-stage pipetting, and resuspension tables. Instance stock edits also apply to nested physical inputs without changing stored inventory.

Multiple cassettes within one parent share a reaction mode. A separate parent preparation requires one cassette enzyme selection and donors for every site that enzyme opens; otherwise it is blocked. Child donors must be fully resolved for their reaction enzyme; recursively editing cassettes inside child donors is not supported.


The plasmid viewer keeps short labels visible, spaces crowded labels into separate rows or columns, and draws connectors to their features. Hover or focus a feature or label to read its full name and coordinates; click to select its sequence. Label placement recalculates when the viewer width changes.

Label-layout checks: `node --test tests/test_map_layout.cjs`.

The plasmid map **Sites** selector shows BsaI, BsmBI, both enzymes, all four detected enzymes, or hides sites. BsaI and BsmBI have separate colors and site counts; labels share the non-overlapping feature layout in circular and linear views. Markers identify recognition-site starts (1-based), rather than phosphodiester cleavage positions. Hover or focus shows motif, strand, and the enzyme’s site count; click highlights the recognition sequence. Circular-origin-spanning sites retain wrapped coordinates and highlight either portion when viewed. Counts reflect the displayed assembled or stored sequence, including retained nested sites.

On the Fragments tab, **Apply rules** opens a custom rule editor for the checked rows only. Applying recalculates and persists stock and resuspension from the current yield and physical DNA length, preserving the yield lock and original uploaded yield. Each selected row retains its applied rules; other rows and the global Rules editor are unchanged. If any selected row is infeasible or unavailable, no rows in the batch change. Pending autosaves finish before applying. These concentrations are labelled as unmeasured plans and can be used by the reaction planner’s saved-stock mode. **Set Default** clears the selected custom plans and restores original yields and current global default calculations. Under fragment names, enzyme flags show all detected BsaI, BsmBI, BbsI and HindIII sites regardless of the selected digestion enzyme; absent enzymes are omitted. Stock warnings and save state appear with quantities/actions.

Plate uploads have **Import rules** flags in the same format as Custom resuspension: DNA input, ratio, target volume, aliquot range, and resuspension cap. Click a flag to edit or reset its values. Preferences persist in the user sandbox separately from reaction-planner preferences and shared global rules. Editing a flag with a selected file refreshes its preview; imports use the latest previewed settings. New rows retain those rules in SQLite so library calculations match the import preview, with plans labelled unmeasured. Supplied stock concentrations and existing duplicate rows remain intact. The resuspension download uses the import settings. Import rules accept the same unrestricted positive values as the library and planner.

Plasmid cards in Uploads and Fragments have editable names and icon controls. Edit the name, toggle circular/linear topology or backbone-template status, and click the disk icon to save the combined changes; Enter in the name field also saves. Unsaved edits and card selections carry between the two tabs. The eye opens the saved sequence and the download icon exports its saved GenBank. Backbone mode forces circular topology; switching to linear clears backbone mode. Unavailable backbone templates are disabled with an explanatory tooltip. Click a card background to toggle selection, drag a rectangle to select cards, or hold Shift/Ctrl/Cmd while dragging to add to the selection. Space/Enter toggles a focused card; Ctrl/Cmd+A selects all and Escape clears selection. Selection and editing controls operate separately. The upload topology controls use matching icons for file topology, circular, linear, and backbone-template status.

Saved plasmids open in a modal viewer with Back, Close, and GenBank download.
Closing the viewer restores the previous assembly and map selection. Click the
backdrop or press Escape to dismiss a popup. Plasmid topology, backbone template,
Save, View, and Download controls share the bottom-left action row. The generated
Junction mark and its prompt are in `app/static/assets/`.

## Comparison details

Exact full matches have a green tick. Rounded near matches remain distinct.
Click a match to open a popup with **Fragments** and **Alignment** tabs.
Back, Escape, or a backdrop click closes it. Advanced is disabled and its
optional alignment integration and tools are excluded from the app package.

The green comparison tick sits beside the uploaded filename. A multi-record
file gets a tick only when all of its records have an exact full alignment.
Select completed files with the compact row checkboxes, then use **Export
results → Selected**. **Export results → 100% matches** includes every exact
record across the queue, even without checked rows. The Excel workbook contains
Results, Fragments, Differences, and export metadata. Selected-file exports can
include nonexact results. Near matches rounded to 100% are excluded from the
exact-only export. Exports do not save or modify plasmids or inventory.

Alignment opens an interactive difference navigator. Click a feature or a colored
substitution/insertion/deletion marker, step through differences, filter by type,
zoom the sequence window, or jump to a reference base. The focused view shows the
changed bases and affected annotations; query coordinates refer to the original
upload even for reverse-complemented or rotated alignments. **All differences**
is collapsed by default and opens a selectable table. Comparison remains read-only.

File rows expand in place to show their plasmid and assembly matches; there is
no separate sample-results card. Multiple rows can stay open, including while
more files are compared. Multi-record files have record tabs within the expanded
row. Click a match for its Alignment and Fragments popup tabs, or use
the fragment count directly. Checkbox selection and retry/remove controls keep
their independent actions.

Identity percentages are shown as prominent colored text, without separate
coverage boxes, a coverage column, or a color key. Identity below 50% is red,
75% is yellow and 100% is green. Percentage text is reduced by 10% from the
initial large styling. Coverage remains available in comparison exports:
paired reference/query bases divided by the respective molecule length.
An exact-match tick still requires a complete exact alignment.

The alignment overview keeps all annotations in one compact feature track,
including color-coded BsaI, BsmBI, BbsI and HindIII recognition sites. Names,
feature coordinates, affected features, cleavage bonds and overhangs appear in
hover/focus cards, with no permanent feature labels or separate Ref/Query RE
tracks. Query-only sites are projected onto the same alignment track and
identified in the hover card. Click an RE marker to inspect the sequence window;
recognition bases are colored, with solid top-strand and dashed bottom-strand
cut marks. Escape dismisses the hover card before closing the comparison.
Cut offsets follow [NEB recognition specificities](https://www.neb.com/en-us/tools-and-resources/selection-charts/alphabetized-list-of-recognition-specificities).


## Bench exports

Use **Export ▾** in Build list, Reaction planner, Resuspension, Fragments or a
completed plate import to select **PDF**, **Excel** or **CSV**. Build-list exports
include every queued assembly; assembly exports include the current draft and
any physically separate nested reactions. Fragment exports use saved library
stocks and the current plate filter. Exporting never changes inventory.

The compact bench guide lists each fragment, its plate alias and well, stock
concentration, total resuspension volume, and per-reaction transfer volume.
Assembly guides add master mix + reagents, water, and total volume. The default
ratio is 1:1 and the default other reagents volume is 4 µL; existing saved plans
keep their chosen values. Current custom ratios and instance stock overrides
are labeled and respected. Unknown stocks or incomplete/overfilled reactions
remain flagged instead of receiving invented volumes.

Plate aliases use the first four alphanumeric characters after `pSHPs`. Colliding aliases receive
numbered suffixes. PDF/Excel plate cells share a color key linking aliases to
full identifiers; CSV includes full identifiers and color codes because CSV
does not carry cell formatting. Assembly exports open on **Assemblies**, then
**Fragment metadata** and **Plate key**. Inventory exports keep **Bench guide**.
The existing detailed calculation sheets remain available and editable; the
new transfer and metadata tables are export snapshots.
The worksheet APIs accept `?format=xlsx`, `?format=pdf` or `?format=csv`.
PDF generation uses ReportLab, installed with the app requirements.

## Plate well lists

Use **Export** in the plate viewer for PDF, Excel or CSV. PDF and Excel include
an image of the displayed 96/384-well layout and the full plate identifier.
CSV downloads a ZIP containing `wells.csv`, the plate map PNG and
a calculation note. Every occupied well is listed, including labelled archived
wells. The separate raw plate CSV download remains available in Uploads.

Well lists use current inventory stock and resuspension values (saved or
planned) and calculate transfer volumes for **0.05 pmol per fragment**, a 1:1
ratio to a 0.05 pmol backbone. Mass uses the full physical construct length
including adapters. Missing values remain blank; transfers outside 1–5 µL,
insufficient yield and palindromic overhangs are flagged. The well table keeps
detected enzymes and terminal overhangs; detailed site-location tables are not
included. Exports never change inventory.

## Assembly tables and build settings

Use **Next** to proceed from Build to Reaction planner to Export assemblies.
Next and tab selection open each view directly. After choosing PDF, Excel or
CSV from Export, the app saves pending edits, refreshes plans and shows any
sequence, stock and reaction warnings in a popup before downloading. Continue
exports the selected format; Back, Escape or clicking outside cancels the
download. The popup also flags an unqueued current assembly. Next does not add
assemblies to the build list.

**Export assemblies** is the dedicated third tab beside Build and Reaction
planner. It shows every queued build's settings, input volumes, readiness,
fragment metadata and plate key. Its Export menu downloads the full list in
PDF, Excel or CSV. Filenames include the browser’s local date and a fresh UUID for each download, for example `Build_list_2026-10-28_BL-8bba366e2dc74238a7bfefc2d394338c.pdf`. Every export gets a unique identifier, including repeated downloads of an unchanged list and exports in different formats. Direct API exports without a date use Australia/Melbourne. PDF pages and Excel print settings use compact A4 portrait tables. Transfer tuples share lines in assembly order, while plate text colors remain consistent with the metadata and plate key. Tables wrap and continue over additional pages as needed. Build and Reaction planner have no assembly-export buttons.

The Name field updates automatically when fragments are added, swapped,
reordered or removed, including changes to the backbone and nested inserts.
Editing the name manually protects it from later changes. This mode persists
in drafts and queued builds; existing custom names remain protected. Clicking
the recommendation resumes automatic naming. Names fit the 100-character limit.

Each reaction occupies one row. Its inputs are listed in assembly order as
`(PlateID-Well-Volume)`; volumes are µL. Plate labels use the first four
alphanumeric characters after `pSHPs`, e.g. `pSHPs0405B231201IQ` becomes `0405`. The color-coded
plate key preserves full IDs and disambiguates collisions. Unlocated backbones
use their name and `—` for the well; unavailable transfer volumes use `?`.
Fragment metadata prints eight columns: name, type, plate, well, physical length,
stock concentration, resuspension volume and yield. Stock basis and assembly
ownership remain in CSV and in hidden Excel columns I:J, and appear on hover
in the app. Repeated ownership text does not increase printed row heights.
Different stocks of the same fragment remain separate records. Separate-first
nested reactions have their own rows. Excel keeps the supporting calculation
sheets; CSV has labelled Assemblies, Fragment metadata and Plate key tables.

Edit Build plans cells to set individual DNA inputs, ratios, other reagents,
total volumes or backbone stocks. Edits autosave and recalculate DNA and water.
The Reaction card detects distinct backbones in the list; a stock entered
there applies to all builds using that backbone without changing their other
settings. Individual build stock cells can override this. Mixed stocks are
marked. Inventory is unchanged, and exports wait for pending edits.

The difference viewer uses one fixed column width across reference, connector
and query tracks, with cut markers anchored to column boundaries. Window and
slider bounds share the same alignment-column calculation, including indels.

## Imported annotations

Uploaded GenBank annotations appear in both circular and linear plasmid views.
Short annotations remain visible, overlapping features use separate tracks, and
joined features retain their separate segments, including across the origin.
Hover for the feature type, strand, coordinates and qualifiers; click to select
its sequence. The collapsible Annotations list includes source and remote
annotations as well as mapped features. Imported hex feature colours are kept.

Re-uploading an annotated plasmid with the same name and sequence enriches its
existing record without duplicating features or replacing stock, location or
assembly metadata. Re-uploading FASTA does not clear saved annotations.

## Reverse-complement matching

Fragment search and quick swaps check both orientations, swapping and reverse-
complementing the two fusion labels when a donor is reversed. The ordered
assembly checks the complete fragment sequence in that orientation; it never
treats complementary labels as an unchanged-fragment match. Compatible supplied
orientations are preferred when both fit. RC bubbles beside fragment status
icons identify reversed donors, including nested inserts. GenBank exports retain
reverse strands, and physical inventory sequences and stock values are unchanged.


The Compare alignment viewer separates annotations into a compact **Features** subtrack and enzyme detections into **Sites**. Each sequence block also has a thin feature band, with overlapping and joined annotations kept distinct and names available on hover/focus. Recognition sites use continuous colored spans; connected solid/dashed cut brackets indicate the top/bottom cuts at aligned base boundaries. Feature endpoints exclude trailing alignment gaps, and cut graphics retain their coordinates when moving the window or crossing a line/origin boundary.


The Compare sequence view shows one continuous alignment per window, with a single reference-position ruler shared by Reference and Query. Reverse-complement queries are labelled **Query (RC)** and use the already oriented alignment. Original uploaded-query positions remain in hover details and difference tables; reverse coordinates display in descending order. The default view is 60 columns; wider windows scroll horizontally with row labels fixed at the left.

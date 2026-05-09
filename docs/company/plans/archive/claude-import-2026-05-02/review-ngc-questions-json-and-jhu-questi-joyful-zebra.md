# JHU_Questions.json — Country-Specific Address Fields (Full NGC Parity)

## Context

`JHU_Questions.json` drives a Johns Hopkins University job application form. When an applicant selects **Canada** (or any country other than the US), only `Q_ADDRESS_1`, `Q_ADDRESS_2`, `Q_CITY`, `Q_POSTAL_CODE` appear — there is no province/territory dropdown. The comparable `NGC_questions.json` correctly shows country-specific state/province/region dropdowns for 19 countries.

**Decisions confirmed with user:**
- Scope: Full NGC parity (add every country subdivision dropdown NGC has).
- `Q_COUNTY` (currently Maryland-only, fires for all US applicants) stays as-is.

## Root Cause

Two coordinated gaps in JHU_Questions.json:
1. The `fields` array defines only US states (as `Q_STATE_TERR_TEXT`) and Maryland counties (as `Q_COUNTY`). No other country's subdivisions exist.
2. The 245 non-US entries in `question_dependencies` all reference the same 4 child_question_ids with no state field.

## Naming Conflicts to Resolve

Two JHU ↔ NGC question_id collisions need renaming before adding NGC's dropdowns wholesale:

| question_id | JHU usage | NGC usage | Resolution |
|---|---|---|---|
| `Q_STATE_TERR_TEXT` | US states (`USA-*`) | Australian states (`AUS-*`) | Rename JHU's existing field to `Q_STATE_REQUIRED` (matches NGC convention). Use `Q_STATE_TERR_TEXT` for Australia going forward. |
| `Q_COUNTY` | Maryland counties | Irish counties (`IRL-*`) | Keep JHU's Maryland `Q_COUNTY` (per user's decision). Rename NGC's Irish dropdown to `Q_COUNTY_IRL` when importing. |

## Plan

### Step 1 — Rename JHU's existing US state dropdown

In [JHU_Questions.json](JHU_Questions.json), rename `Q_STATE_TERR_TEXT` → `Q_STATE_REQUIRED` everywhere it appears:

- Field definition at [JHU_Questions.json:1013-1259](JHU_Questions.json#L1013-L1259) — change `question_id` value.
- Set `"required": true` (matches NGC; US state is required there).
- US dependency at [JHU_Questions.json:4327-4339](JHU_Questions.json#L4327-L4339) — replace `"Q_STATE_TERR_TEXT"` with `"Q_STATE_REQUIRED"` in `child_question_ids`.

### Step 2 — Add 19 country subdivision dropdowns to the `fields` array

Copy each dropdown verbatim from NGC into JHU's Address section (before `Q_POSTAL_CODE` at line 1261). The source line ranges in NGC:

| New question_id in JHU | Country | Copy from NGC lines |
|---|---|---|
| `Q_PROV_TERR` | Canada (CA) | 9157-9216 |
| `Q_STATE_BRA` | Brazil (BR) | 9523-9636 |
| `Q_STATE_MYS` | Malaysia (MY) | 9639-9708 |
| `Q_STATE_NGA` | Nigeria (NG) | 9711-9864 |
| `Q_STATE_TERR_TEXT` | Australia (AU) | 10121-10158 |
| `Q_COUNTY_IRL` (renamed from `Q_COUNTY`) | Ireland (IE) | 5978-6104 |
| `Q_COUNTY_CITY` | Taiwan (TW) | 6107-6905 |
| `Q_PROV_DOM` | Dominican Republic (DO) | 7511-7685 |
| `Q_PROV_ITA` | Italy (IT) | 7687-8220 |
| `Q_PROV_PAN` | Panama (PA) | 8223-8284 |
| `Q_PROV_PNG` | Papua New Guinea (PG) | 8287-8380 |
| `Q_PROV_THA` | Thailand (TH) | 8383-8700 |
| `Q_PROV_ZWE` | Zimbabwe (ZW) | 8703-8748 |
| `Q_PROV_CITY_CHN` | China (CN) | 8751-8892 |
| `Q_PROV_CITY_VNM` | Vietnam (VN) | 8895-9156 |
| `Q_REGION_TZA` | Tanzania (TZ) | 9219-9348 |
| `Q_REGION_UKR` | Ukraine (UA) | 9351-9464 |
| `Q_REGION_UMI` | U.S. Minor Outlying Islands (UM) | 9467-9520 |

**Excluded** (NGC defines these as empty dropdowns — a bug we won't replicate): `Q_STATE_TERR_CHRIST_ISLAND` (Christmas Island), `Q_STATE_TERR_COCOS` (Cocos Islands). Those two countries keep the basic 4-field layout.

Set `"required": false` on each to match NGC (keeps entry-flow forgiving for international applicants).

### Step 3 — Wire 19 dependencies in `question_dependencies`

For each country below, update its `child_question_ids` in JHU's `question_dependencies` array to insert the subdivision dropdown between `Q_CITY` and `Q_POSTAL_CODE` (preserving JHU's existing 4-field order):

```
Q_ADDRESS_1, Q_ADDRESS_2, Q_CITY, <SUBDIVISION>, Q_POSTAL_CODE
```

Country-by-country field insertions:

| ISO | Country | Insert into child_question_ids |
|---|---|---|
| CA | Canada | `Q_PROV_TERR` |
| BR | Brazil | `Q_STATE_BRA` |
| MY | Malaysia | `Q_STATE_MYS` |
| NG | Nigeria | `Q_STATE_NGA` |
| AU | Australia | `Q_STATE_TERR_TEXT` |
| IE | Ireland | `Q_COUNTY_IRL` |
| TW | Taiwan | `Q_COUNTY_CITY` |
| DO | Dominican Republic | `Q_PROV_DOM` |
| IT | Italy | `Q_PROV_ITA` |
| PA | Panama | `Q_PROV_PAN` |
| PG | Papua New Guinea | `Q_PROV_PNG` |
| TH | Thailand | `Q_PROV_THA` |
| ZW | Zimbabwe | `Q_PROV_ZWE` |
| CN | China | `Q_PROV_CITY_CHN` |
| VN | Vietnam | `Q_PROV_CITY_VNM` |
| TZ | Tanzania | `Q_REGION_TZA` |
| UA | Ukraine | `Q_REGION_UKR` |
| UM | U.S. Minor Outlying Islands | `Q_REGION_UMI` |

The US entry was already updated in Step 1 (rename only).

**Explicitly NOT changing:** the 225 other countries keep their existing 4-field `[Q_ADDRESS_1, Q_ADDRESS_2, Q_CITY, Q_POSTAL_CODE]` dependency — those countries don't have a subdivision dropdown defined in either file.

### What we're NOT doing (out of scope per user decision)

- Not replicating NGC's country-specific **name fields** (Kanji, Cyrillic, Thai script, preferred-name variants). Those are a separate feature.
- Not replicating NGC's country-specific **address line / city variants** (`Q_STREET_NAME`, `Q_CITY_COMMUNE`, `Q_DISTRICT`, `Q_SUB_LOC`, etc.). JHU keeps its generic 4-line address for all countries.
- Not replicating NGC's **reordered or minimal address flows** (e.g., Taiwan's postal-code-first, Panama's 2-field address). All JHU countries keep the standard field order.
- Not modifying `Q_COUNTY` (Maryland) behavior.

## Files Modified

- `c:\Users\hadam\Documents\Customers\JHU_Questions.json` — one file, ~1100 lines of additions (18 new dropdown definitions) + 19 dependency edits + 1 rename.

## Verification

1. **JSON validity**: `python -c "import json; json.load(open('JHU_Questions.json'))"` — must succeed.
2. **No orphan question_ids**: every question_id referenced in `question_dependencies` must exist in `fields`. Grep each new ID; expect exactly two hits (definition + dependency).
3. **No lingering old `Q_STATE_TERR_TEXT` with `USA-*` values**: confirm the rename is complete. Grep for `"USA-AL"` — should hit only inside the renamed `Q_STATE_REQUIRED` block.
4. **Manual form check** (ideal): load JHU's smart_apply form and verify:
   - Country = Canada → "Province or Territory" dropdown appears with 13 choices.
   - Country = United States → US state dropdown (now `Q_STATE_REQUIRED`) + Maryland county appear.
   - Country = Australia / Brazil / Italy / Ukraine / etc. → their corresponding dropdown appears.
   - Country = France (untouched) → only the 4 basic address fields.
5. **Choice-level diff** against NGC: `diff` each new dropdown's choices array vs NGC's source — same values, same labels.

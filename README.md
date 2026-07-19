# Renesas CMSIS SVD collection

Local collection of CMSIS SVD files for Renesas RA, RZ/T2 and RZ/N2 devices,
extracted unmodified from vendor packs. Built 2026-07-19.

## Coverage

| Family | SVD files | Notes |
|--------|-----------|-------|
| RA     | 40        | Covers all 114 RA catalog devices. The pack ships one SVD per device group, `also_covers` in manifest.json lists the extra part numbers each file serves. |
| RZT    | 14        | RZ/T2L, RZ/T2M, RZ/T2ME, RZ/T2H (R9A07G074x, R9A07G075x, R9A09G077M). |
| RZN    | 3         | RZ/N2L, RZ/N2H (R9A07G084x, R9A09G087). |

Total: 57 files, about 376 MB.

## Sources

1. Renesas RA Device Family Pack (RA_DFP) 6.5.1, released 2026-06-06.
   - pdsc: https://www2.renesas.eu/Keil_MDK_Packs/Renesas.RA_DFP.pdsc
   - pack: https://www2.renesas.eu/Keil_MDK_Packs/Renesas.RA_DFP.6.5.1.pack
   - sha256: c5f3a3308426cb7667d599d9b88c810c4f4c6c2627baf33b8f7d050b8a72afd9
   - Extracted: `SVD/*.svd` (40 files) into `RA/`.
2. renesas/rzt-fsp GitHub release v3.1.0, asset RZT_FSP_Packs_v3.1.0.zip.
   - https://github.com/renesas/rzt-fsp/releases/download/v3.1.0/RZT_FSP_Packs_v3.1.0.zip
   - sha256: 4e95b6f2665b890b197a9a0f17b2a5124fc5a36d9de163a3f4f9fda12d227526
   - SVDs live one level down, inside nested `Renesas.RZT_mcu_*.3.1.0.pack`
     zips under `internal/projectgen/rz_fsp/rzt/packs/`, at `.mcu/.iofiles/*.svd`.
     14 files into `RZT/`.
3. renesas/rzn-fsp GitHub release v3.1.0, asset RZN_FSP_Packs_v3.1.0.zip.
   - https://github.com/renesas/rzn-fsp/releases/download/v3.1.0/RZN_FSP_Packs_v3.1.0.zip
   - sha256: 6ca395e8a560775a9a5835d5850c248dbf098a52a23207a1c9fefab4935fc732
   - Same nested layout as rzt-fsp. 3 files into `RZN/`.

## LICENSE & REDISTRIBUTION STATUS

**RA_DFP: no license found. Treat as Renesas-proprietary. Do not publish
publicly without legal review.** This repo is a local collection only.
Evidence, checked on 2026-07-19:

- The pdsc contains an empty license element, literally `<license></license>`.
- A search of every member of Renesas.RA_DFP.6.5.1.pack for names containing
  license, eula, terms, notice or copying found nothing.

So there is no license text to quote and no redistribution grant of any kind
for the RA SVD files.

**rzt-fsp and rzn-fsp: BSD-3-Clause for the Renesas BSP components, per the
repo LICENSE.md at tag v3.1.0** (copied to `LICENSES/rzt-fsp-LICENSE.md` and
`LICENSES/rzn-fsp-LICENSE.md`). The license table in both files lists
"RZ/T MPU BSP" (and RZ/N respectively), copyright "Renesas Electronics
Corporation", license "BSD-3-Clause". The BSD text in those files starts:

> Copyright 2020 - 2025, Renesas Electronics Corporation and/or its affiliates
>
> Redistribution and use in source and binary forms, with or without
> modification, are permitted provided that the following conditions are met: ...

Caveats: the nested mcu packs that actually carry the SVD files contain no
license file of their own (checked), and LICENSE.md does not name SVD files
explicitly. The SVDs ship as part of the MPU BSP packs which the table covers,
so BSD-3-Clause is the reasonable reading, but it is an inference. Keep the
LICENSES/ copies with any redistribution.

## Refresh

    python fetch.py

Stdlib only, no third party packages. Downloads are cached in `.work/`,
delete that folder to force a re-download. The script picks the newest
release version from the pdsc and the latest GitHub release automatically,
then validates every SVD (well formed XML, root element `device`) and
rewrites manifest.json. Invalid files are deleted and logged under
`issues` in the manifest.

The fetch is incremental: it checks the upstream versions first and only
downloads the sources that actually changed, printing "up to date" and
touching nothing when there is nothing new. A GitHub Action
(`.github/workflows/check-updates.yml`) runs it weekly on Monday at
06:00 UTC and commits any updates.

## Provenance legend

- pristine: byte-identical to the file inside the vendor archive. Everything
  in this collection is pristine.
- patched / community / converted: not used here.

## Known gaps

- No license grant for the RA files (see above).
- RA has one SVD per device group, not per catalog part number. Memory size
  variants share one file. Use `also_covers` in manifest.json to resolve a
  part number to its file.
- Only RA, RZ/T2 and RZ/N2 are included. Other Renesas lines (RX, RL78,
  RZ/A, RZ/G, RZ/V, Synergy, DA) are out of scope for this collection.
- The RZ SVD set is whatever the FSP mcu packs ship, it may not cover every
  RZ/T or RZ/N part number.

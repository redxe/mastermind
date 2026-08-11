# Source verification record (2026-08-11)

Method: load-bearing entries fetched from arXiv abstract pages or DOI resolution on 2026-08-11. "DOI resolves" means the DOI redirected to the correct journal's article page (full metadata behind paywall/403 was not re-checked field-by-field). No new citations were added without verification; no metadata was invented — unverifiable fields were removed rather than guessed.

## Verified against source (fetched this session)

| Key | Claim it supports | Verification | Corrections applied |
|---|---|---|---|
| beverland2022 | Resource-estimation framework across the stack (§2 related work, §4, §13) | arXiv 2211.07629 abstract page fetched; title and full author list confirmed | Author "Aravind Sundaram" → **Aarthi Sundaram** |
| vandam2024 | Azure Quantum Resource Estimator methodology (§4, §7) | arXiv 2311.05801 fetched; title is "…Fault Tolerant Quantum Computation" (no hyphen); ACM TQC publication could not be confirmed | Entry changed @article→@misc (arXiv); unverified journal claim removed; title corrected |
| brunet2023 | Radio-astronomy encoding comparisons (§10) | arXiv 2310.12084 fetched; full author list confirmed; published version DOI 10.1016/j.ascom.2024.100796 (Astronomy and Computing) listed as Related DOI | Upgraded to published @article with verified DOI; "and others" replaced with full author list; volume omitted (not verified) |
| nqiworkshop2025 | Community assessment of algorithmic priorities (§13) | arXiv 2508.13973 fetched; real title and author list (Kapit, Love, Larson, Sornborger, Crane, Schuckert, Tomesh, Chong, et al.) confirmed | Corporate-author placeholder replaced with verified authors; full title restored |

## DOI resolution checked (redirects to correct journal)

| Key | Claim | Check |
|---|---|---|
| acharya2025 | Below-threshold surface-code scaling, correlated-error floors (§4) | 10.1038/s41586-024-08449-y resolves to nature.com article (Nature) |
| meth2025 | Qudit lattice-gauge encoding overhead (§9) | 10.1038/s41567-025-02797-w resolves to nature.com article (Nature Physics) |
| gao2022 | Grover-style GW template search (§10) | 10.1103/PhysRevResearch.4.023006 resolves to link.aps.org (PRResearch); page fetch blocked (403), metadata not field-checked |

## Held over from earlier verification / standard canonical entries (not re-fetched this session)

feynman1982, shor1997, grover1997, brassard2002, harrow2009, gilyen2019, low2019, peruzzo2014, cerezo2021, mcclean2018, wang2021, preskill2018, fowler2012, cai2023, quek2024, gidney2021, tang2019, tang2021, aaronson2015, montanaro2016, chen2023, eisert2020, quetschlich2023, lykhov2023, fuchs2024, dimeglio2024, bauer2023prx, bauer2023nrp, miyamoto2022 — canonical, widely cited entries whose DOIs follow publisher patterns; each supports the claim stated at its citation site. **TODO (author): spot-check these DOIs before submission**; none is currently known to be wrong.

nasaquail2026, born1954, pauli1946, nobelhistory2000, feynmanlosalamos, paulieffect — web/lecture sources with access dates recorded in the .bib; support only historical/contextual claims.

## Claims deliberately left uncited

- Grouped-measurement shot-allocation literature (classical shadows, importance weighting): the manuscript derives its own elementary bounds rather than citing this literature; adding a survey citation here is flagged as an author TODO in the text (a specific primary source was not verified this session, and citing one unverified would violate the no-fabrication rule).
- Quantum bioinformatics cost comparisons (§8): explicit TODO in text; no citation added.

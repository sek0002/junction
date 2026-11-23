# mRNA reference data

`csc_wu2019.csv` is unchanged Figure 1 source data 2 from Wu et al., *Translation affects mRNA stability in a codon-dependent manner in human cells*, eLife 8:e45396 (2019).

- Article: https://doi.org/10.7554/eLife.45396
- Dataset DOI: https://doi.org/10.7554/eLife.45396.006
- Download: https://cdn.elifesciences.org/articles/45396/elife-45396-fig1-data2-v2.csv
- Retrieved: 23 November 2026. The UI uses the mean `293T_ORFome` coefficient over sense codons, excludes stop codons and applies this human reference only to human designs.

`elements.json` contains UTR, Kozak and poly(A) components transcribed from the user-supplied mRNArchitect v5 supplementary Table S4 (`media-5.xlsx`). It retains the tested construct labels. A preset's 5′ field includes its Kozak sequence. These are reference sequences, not an assurance of performance in other constructs or cells.

The BASE application code is **not** bundled here. It stays in a separately authorised private checkout. The connector imports it only at runtime.

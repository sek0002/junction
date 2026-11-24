# mRNA reference data

`csc_wu2019.csv` is unchanged Figure 1 source data 2 from Wu et al., *Translation affects mRNA stability in a codon-dependent manner in human cells*, eLife 8:e45396 (2019).

- Article: https://doi.org/10.7554/eLife.45396
- Dataset DOI: https://doi.org/10.7554/eLife.45396.006
- Download: https://cdn.elifesciences.org/articles/45396/elife-45396-fig1-data2-v2.csv
- Retrieved: 23 November 2026. The UI uses the mean `293T_ORFome` coefficient over sense codons, excludes stop codons and applies this human reference only to human designs.

`elements.json` contains UTR, Kozak and poly(A) components transcribed from the user-supplied mRNArchitect v5 supplementary Table S4 (`media-5.xlsx`). It retains the tested construct labels. A preset's 5′ field includes its Kozak sequence. These are reference sequences, not an assurance of performance in other constructs or cells.

`utrs.json` exposes these components separately for each UTR end and adds native human **HBA1** and mouse **Hba-a1** UTRs. Native sequences were retrieved from NCBI RefSeq GenBank records on 24 November 2026; coordinates are 1-based, inclusive:

| Species | Reference | 5′ UTR | 3′ UTR |
| --- | --- | --- | --- |
| Human | [NM_000558.5](https://www.ncbi.nlm.nih.gov/nuccore/NM_000558.5) | 1–37 (37 nt) | 467–577 (111 nt) |
| Mouse | [NM_008218.2](https://www.ncbi.nlm.nih.gov/nuccore/NM_008218.2) | 1–35 (35 nt) | 465–557 (93 nt) |

Native UTRs exclude the annotated CDS, including its stop codon. The 3′ sequence ends at the annotated poly(A) site: the 12 terminal A residues beyond mouse position 557 are excluded, and poly(A) length is controlled separately. Native 5′ UTRs retain their reference initiation context without an added Kozak sequence. SHA-256 checksums and accession coordinates accompany each native entry. The paper entries retain engineered Kozak sequences, cloning linkers and other labelled components; the paper's common 3′ component is mouse α-globin with a cloning linker. Selecting a preset changes only that UTR end and preserves the other end and poly(A) setting. Existing combined `elements` capability data remain available for compatibility.

The BASE application code is **not** bundled here. It stays in a separately authorised private checkout. The connector imports it only at runtime.

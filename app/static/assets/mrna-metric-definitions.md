# mRNA metrics and radar scales

The mRNArchitect v5 manuscript reports Figure 1b's five radar axes on a 0–1 scale and Figure 1c's absolute measurements. Its methods used mRNArchitect v1.4.1. The supplied local BASE installation is v1.0.2; its source does not expose Figure 1c's homopolymer count or percentage manufacturability score. The manuscript does not specify their counting/aggregation formulas or the radar transformations. Junction therefore identifies its additional definitions explicitly rather than claiming numerical reproduction of that figure.

## Measured/computed quantities

- **GC content:** 100 × (G + C nucleotide counts) / CDS length. RNA U is treated as DNA T.
- **CAI:** the geometric mean of codon weights. A codon's relative weight is its organism-specific usage divided by the largest synonymous codon usage for that amino acid. Junction calls BASE's `compute_cai` with the selected organism table. The paper uses Kazusa codon usage. A high CAI indicates preference for common synonymous codons; it is not a direct measurement of translation.
- **MFE/nt:** ViennaRNA's predicted minimum folding free energy in kcal/mol, divided by the length of the folded sequence. More negative values indicate a more favourable predicted folded state. The paper evaluates the CDS; choose CDS folding to compare on that basis. Junction's full-transcript folding option instead includes its UTRs and poly(A) tail.
- **DegScore half-life (model h):** the installed DegScore 2.1 model sums its per-position degradation scores over the selected folded sequence, then uses `k = 0.002170959651184987 × DegScore + 0.05220886935630193` and `t½ = ln(2)/k`. The calibration describes accelerated chemical degradation (10 mM MgCl₂, Na-CHES pH 10.0, 24 °C), not intracellular persistence or a prediction adjusted to the UI folding temperature. CDS folding scores CDS only; full-transcript folding includes UTRs and poly(A). The sum is length dependent, so compare matched sequences with consistent scope. Invalid/nonpositive estimates are unavailable. [Official calibration and formula](https://github.com/eternagame/superfolder-covid-mrna-vaccines/blob/main/analysis/README.md#estimating-half-life-from-degscore).
- **RiboNN translation:** raw ensemble model output for the selected cell/tissue, or the arithmetic mean across targets. The radar rescales this raw value using the editable range; a radial score is not a translation probability. Prediction requires both UTRs and a terminal stop codon.
- **Homopolymer nt (Junction definition):** total nucleotides in maximal CDS runs of at least two identical bases, counting each base once. `ATGAAAACCTAA` includes four A bases, two C bases and its final two A bases: 8 nt. This total is distinct from the count of runs exceeding manufacturing thresholds. The intentional transcript poly(A) tail is excluded.
- **Manufacturability % (Junction definition):** `100 × (1 − B/L)`, where L is CDS length and B is the union of CDS positions in DNA Chisel's reported violation locations. Overlapping locations count once. Checks use each row's configured global/windowed GC limits, homopolymer thresholds, repeated k-mers (including reverse complements), hairpins and excluded motif/restriction patterns. No enabled checks yields an unavailable score, rather than an assumed 100%. A failed global GC constraint marks the full CDS. This is an aggregate constraint-coverage proxy, not a synthesis yield/success probability or the paper's unspecified formula. The per-check native scores and locations are retained in the design-quality report.

Manufacturing checks invoke the installed BASE constraint builder and DNA Chisel's `EnforceGCContent`, `AvoidPattern`, `AvoidHairpins`, and `UniquifyAllKmers`. Protein preservation and CAI/tAI objectives are excluded from this manufacturing score. Repeat specifications are evaluated for the report, including when the older BASE optimiser treats them as soft objectives. Configuration and library versions are retained for reproducibility.

## Radar transformations

The default checkboxes select GC, homopolymer, manufacturability, CAI and MFE/nt. It reproduces the axis categories, with explicitly defined Junction scores and plotting ranges.

Every axis has editable bounds. Higher-is-outside uses `(x − min)/(max − min)`; lower-is-outside uses `(max − x)/(max − min)`. Target mode rises linearly from 0 at min to 1 at target and declines to 0 at max. All radii are clipped to [0,1]; the interface reports clipping. These hypothetical guide ranges remain fixed when samples are deselected. They are not validated universal biological optima.

| Parameter | Default reference range | Outer edge |
|---|---|---|
| GC | 40–70% | Target 60% |
| Homopolymer | 0–100% of CDS bases in runs ≥2 | Lower burden |
| Manufacturability | 0–100% coverage proxy | Higher |
| CAI, tAI | 0–1 | Higher |
| MFE/nt | −0.5–0 kcal/mol/nt | More negative |
| Whole-sequence MFE | −1000–0 kcal/mol | More negative |
| Predicted half-life | 0–2 model hours | Higher |
| Human codon stability coefficient | −0.1–0.1 | Higher |
| RiboNN translation | 0–5 model units | Higher |
| CDS length | 0–8000 nt | Larger magnitude |

Homopolymer raw values remain nucleotide counts in the table; radar normalisation uses `100 × homopolymer_nt/CDS_length` to compare different lengths. CAI/tAI and GC reference ranges do not imply that maximising them is universally beneficial. Half-life, CSC and translation use model/context-specific scores, and their guide ranges should be adjusted for the comparison.

## Heatmap scales

All mRNA heatmaps use the Matplotlib **Inferno** palette. Numeric comparison columns use population z-scores computed independently from selected rows with available scores. Deselected rows are uncoloured. Constant columns have z=0; no available values remain unavailable. The continuous key spans −2 to +2, with colour clipping beyond those bounds.

Hamming colours use the absolute fraction of differing bases, from 0 (identical) to 1 (all different). Unequal lengths are unavailable and are not assigned a colour. Structure and sequence colours use the same available native per-nucleotide DegScore degradation contributions across the batch: brighter Inferno colours indicate lower predicted degradation contribution, hence greater predicted stability. These contributions are not thermodynamic energies or measured cellular half-lives.

## Sources

- [mRNArchitect manuscript, Figure 1 and Methods](https://doi.org/10.1101/2024.12.03.626696).
- [DNA Chisel GitHub repository](https://github.com/Edinburgh-Genome-Foundry/DnaChisel).
- [DNA Chisel specification documentation](https://edinburgh-genome-foundry.github.io/DnaChisel/ref/builtin_specifications.html).
- [Matplotlib's Inferno colour data](https://github.com/matplotlib/matplotlib/blob/main/lib/matplotlib/_cm_listed.py).

The radar shows paired raw translation/half-life values and the current bounds when either axis is selected. “Fit translation axis” and “Fit half-life axis” explicitly replace that axis’s bounds with the matched pair’s minimum/maximum plus padding; no scientific scores change. Fitted ranges persist in worksheets. Reset reference ranges restores the fixed guides above.

The 0–2 model-hour half-life guide is intended for typical full-length constructs (the model’s published long-mRNA examples are approximately 0.2–0.6 h); short CDS inputs can exceed it. The 0–5 translation guide covers the means and cell-specific scores checked during this release. It is an empirical display guide, not a biological maximum: negative or >5 model predictions remain unchanged and are flagged as clipped. Older untouched 0–24 h and −3–3 translation guides migrate to these bounds; custom ranges are preserved.

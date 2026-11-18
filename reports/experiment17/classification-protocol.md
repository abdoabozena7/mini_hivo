# Experiment 17 — deterministic classification checkpoint

This is a **partial** result. The protocol reused nine frozen approved execution contracts: three Timer instances from Experiment 16 and six game instances from Experiment 15. It compared the existing `current` classifier with the optional `field_scoped` classifier on the same objects. It also changed identity and metadata fields three ways per contract.

| Check | `current` | `field_scoped` |
|---|---:|---:|
| Timer contracts classified as Timer | 0/3 | 3/3 |
| Game contracts classified as game | 6/6 | 6/6 |
| Identity perturbations preserving `field_scoped` classification | — | 27/27 |

The exact contract-level rows and hashes are in [classification-protocol.json](classification-protocol.json). These are classifier checks without model calls. They do not measure Worker behavior, Child verification, Root verification, or overall success. Fresh Experiment 17 execution and its final report are pending.

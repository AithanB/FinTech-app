# Stage 12 — Package, demonstrate and rehearse handoff

Status: **passed**. The release candidate is assembled, the saved image loaded
successfully, and the README command passed from a clean canonical checkout.
All required Stage 12 checks ran. No organizer-contract conflict was found.

## Changed files and reading order

1. Root `LICENSE`, `THIRD_PARTY_NOTICES.md`, `docs/design.md`,
   `release/INVENTORY.md` and release instructions at the top of `README.md`.
2. `audit_env/demo.py`, `policies/demo_accusation.py`, `docs/demo.md` and
   `tests/test_stage12.py`: supported finding, correct clean response and one
   valid but false accusation through the same isolated environment/evaluator.
3. Pinned `Dockerfile`, notice preservation and `scripts/export_release_metadata.py`:
   open JSON Schemas, installed dependency inventory and actual license texts.
4. `scripts/package_release.py`: deterministic source/evidence ZIP and complete
   per-file SHA-256 manifest. It includes the complete source snapshot and excludes local secrets,
   caches and archive output.
5. `release/image-lock.json`, `release/rehearsal/`, `evaluator/stage12/demo/`
   and `release/artifacts/`: immutable runtime identity, fresh-checkout evidence
   and final source ZIP, saved image, checksums and measured sizes.

## Rehearsal scope

The release source was snapshotted into an isolated temporary Git repository
and cloned into a clean checkout. The normal README command uses the saved
prepared image without networking, credentials, GPU or host-only mounts/paths. The tested runtime source digest agrees with
the clean source snapshot. The deliberately incorrect Stage 11 expectation
exited **1**, while the original expectation remained unchanged.

The source ZIP and compressed saved image are separate delivery artifacts. The
ZIP has an exact payload manifest. Packaging output is excluded from itself and
from Docker's build context, avoiding recursive inclusion and digest cycles.
The image lock and final rehearsal/study files are excluded from the image so
the tested image identity can be recorded after it exists. These release
artifacts are never inputs to ordinary policy programs.

## Acceptance evidence

The final results live in `release/rehearsal/`; complete Stage 11 evidence remains
in `evaluator/stage11/`. The three demo cases are retained separately in
`evaluator/stage12/demo/`. See `release/INVENTORY.md` for the mapping to every
organizer deliverable and the five rubric categories. The local suite is not
presented as the jury's official hidden checks or a rubric score prediction.

The full portable suite passed **271 tests**, with **20 Linux-only checks
skipped**. The final prepared-image run passed **290 tests**, with **one
Windows-specific guard skipped**, then completed **80** distinct policy/episode
runs and **20** separate transformed pairs. All supported isolation checks ran.
The real timeout/reaping probe, intentionally incorrect expectation rejection,
export byte checks and independent summary/capture checks passed. `pip check`
and `git diff --check` passed. Installed versions were compared against the
delivered dependency lock: **15 Python distributions** and the exact Debian
package inventory agree. **14 JSON Schema files** accompany the source models.

Final image identity:
`sha256:4e1fafa83a0cfa75796cf2c6bedcf5a91d2ce0942e4ce418aacb569795909536`.
The canonical runtime source SHA-256 is
`a10f3c7eb7189b6dbcb81a593107c62e6528a912d9a34a5caaada664ca3a8044`.
All **721 inventoried files** in the rehearsed source snapshot were checked
byte for byte. The isolated rehearsal checkout was clean before and after the run.

Docker inspection recorded network mode `none`, zero host mounts, no GPU device
requests, a two-CPU quota and **4,294,967,296 bytes** RAM. Only image-defined
environment variables were present; no credentials were forwarded. Maximum
episode wall time was **1.2113 seconds**, with an RSS upper bound of
**86,040,576 bytes**. Reconciliation/oracle retained mean F1=1 and returns
**.9689 / 1**; random/mass accusation each averaged **−1**.

The release verification and demo commands were exercised with the
prepared image loaded from the delivered compressed export. The same image's
demo returned **.992**, **.992**, **−1**, with respectively TP/FP/FN
**1/0/0**, **0/0/0**, **0/1/0**. The failed accusation was structurally valid.
The demonstration had no host mounts and public closed rewards stayed zero.

The image occupies **329,528,390 bytes** according to Docker; its saved OCI tar
is **73,449,984 bytes**, and gzip delivery file is **72,930,617 bytes**. OCI layer
blobs are already compressed, explaining why the saved tar is smaller than
Docker's uncompressed image size. Exact final source ZIP size, saved-image size
and both artifact digests are in the delivery directory's `sizes.json` and
`SHA256SUMS`; they are kept outside the ZIP to avoid a self-referential hash.
Both source and runtime delivery artifacts fit within the suggested 1 GB limit.

### Issues found during handoff preparation

Windows initially blocked Git's helper process; the local clone succeeded with
the required tool access. A byte audit then caught CRLF conversions in the Git
checkout and older source/fixture files. The packager emits canonical LF, and
the final clone configured both `core.autocrlf=false` and `core.eol=lf` before
its first checkout. The final image was rebuilt from that canonical source and
the complete offline rehearsal repeated. The source and runtime digests now
agree exactly. Earlier attempts remain under ignored `runs/stage12/`.

The final ZIP adds the retained rehearsal evidence and this handoff note after
execution. Its payload manifest is checked separately; its runtime source digest
is identical to the tested checkout and prepared image. No runtime code changed
after the successful rehearsal.

## Study checkpoint and owner handoff

`docs/demo.md` walks source event → causal mutation → accessible payment and
settlement proof → supported submit → one-to-one match → .992 return at four
inspections. A clean answer earns the same F1 and cost-adjusted return. One
unsupported clean-company accusation is valid JSON but an FP and earns -1.
The trusted oracle shows that correct supported truth can attain return 1 with
one submit; it does not demonstrate ordinary-agent competence or training.

Known limits remain: November 2026 synthetic cases, KZT base currency conventions,
604-row/200-document maximum tested profile, fixed scripted policies and RSS
upper bounds rather than simultaneous memory peaks. A fresh checkout on the
existing Docker/WSL2 host is rehearsed; a different physical machine and a fully
offline image build are not claimed. No model is trained. No push, publication or organizer submission was performed.

The release candidate is ready for submission through the announced channel.
There is no next roadmap stage.

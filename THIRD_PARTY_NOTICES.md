# Third-party notices

The project-authored source, fixtures and synthetic records are under the root
MIT `LICENSE`. Dependencies retain their own licenses and attribution.

`release/dependency-lock.json` records every installed Python distribution and
Debian package in the prepared image, including the separate agent-runtime
builder. `requirements.txt` pins the application/test dependencies. The Docker
base image is pinned by digest in both build stages. The prepared release image
identity is frozen separately in `release/image-lock.json`.

The unmodified license texts discovered in the prepared runtime are delivered
under `release/licenses/`: Python's combined license, Python distribution
LICENSE/COPYING/NOTICE files, Debian copyright files and agent-runtime builder
copyright files. The image also retains its original `/usr/share/doc` notices
and builder notices under `/opt/agent-runtime-licenses`.

Python distribution licenses include their transitive embedded components;
consult the delivered texts and installed metadata for each package. This
inventory describes the shipped runtime and is not a relicensing of those
components. No externally downloaded financial records or model weights are
included.

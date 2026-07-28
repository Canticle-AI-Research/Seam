# Proprietary compiled self-host edition

The compiled self-host edition runs the private SEAM MIRL engine on
customer-controlled Linux/amd64 infrastructure while exposing only the opaque
public `/v1` contract. It is a controlled distribution format, not a
cryptographic black box. Linux/arm64 is not qualified by this first edition.

## Honest protection boundary

The first edition raises the cost of casual inspection and reduces accidental
leakage:

- Nuitka standalone compilation produces a native executable plus runtime
  libraries without shipping `.py`, `.pyc`, specifications, tests, or build
  tools. Nuitka documents standalone output as independent of a target Python
  installation: <https://nuitka.net/user-documentation/user-manual.html>.
- The final image uses the shell-less distroless base runtime, uid 65532,
  read-only root filesystem, no Linux capabilities, and no-new-privileges:
  <https://github.com/GoogleContainerTools/distroless>.
- Only `/v1/health`, `/v1/memories`, `/v1/memories/recall`, and `/v1/context`
  are registered. OpenAPI/docs, dashboard, stats, graph, storage, reasoning,
  benchmark, MIRL, PACK, HS/1, and operator routes are absent.
- An offline Ed25519 entitlement is verified before the server starts. The
  image contains only the public verification key. The customer mounts the
  signed entitlement and API-token secret read-only.
- `verify_selfhost_artifact` inspects the real Docker/OCI archive and fails on
  source-like files, private specifications/docs/tests, shells/package
  managers/interpreters, secret-shaped bytes, root execution, or an unexpected
  entrypoint.

These controls do **not** stop a determined administrator who controls the
host. That administrator can copy the image, observe process memory and system
calls, modify the executable or runtime, replace entitlement checks, or
capture decrypted database content. Offline entitlements are tamper-evident
license controls, not DRM against a hostile owner.

Native compilation is also not source erasure. Compiled artifacts can retain
module filenames, type names, error strings, and other constants even when the
defined symbol table is stripped and no source files are present. Treat those
names as discoverable by a customer with the image.

## Threat model

| Threat | Compiled standard edition | Additional control |
| --- | --- | --- |
| Accidental public registry or package leak | Private registry access, no PyPI path, signed digest, artifact scanner | Rotate registry grants and treat leaked image as an incident |
| Casual source browsing | No Python source/docs/tests in the final image; native compilation; distroless runtime | Keep builder cache and CI logs private |
| Stolen powered-off disk or backup | Customer-managed encrypted data volume | LUKS2/dm-crypt or a cloud encrypted volume with separately controlled keys |
| Unauthorized but non-admin use | Signed, bounded, expiring offline entitlement and bearer API token | Per-customer image/digest and read-only registry credentials |
| Malicious host administrator | **Not protected** | Confidential VM/container, measured boot, attestation, and remote key release |
| Physical/runtime side channels or compromised CPU firmware | Outside this edition's claim | Vendor/platform patching and a separately qualified confidential tier |

LUKS protects data at rest when the volume is locked; it does not hide an
unlocked database from root on the running host. The cryptsetup interface and
LUKS documentation are maintained at
<https://gitlab.com/cryptsetup/cryptsetup> and
<https://man7.org/linux/man-pages/man8/cryptsetup.8.html>.

## Confidential tier, not implemented here

OCI layer encryption can protect image layers in transit and at rest, but a
normal customer-controlled runtime ultimately receives the decryption key and
plaintext. `nerdctl` documents OCIcrypt image encryption support:
<https://github.com/containerd/nerdctl>. Do not market ordinary OCI encryption
as protection from the host administrator.

Host-resistant confidentiality requires a supported TEE such as AMD SEV-SNP or
Intel TDX, an attested guest measurement, and a key broker that releases the
image/data key only to an approved measurement. Confidential Containers'
Trustee architecture separates the Key Broker, Attestation Service, and
reference-value service:
<https://confidentialcontainers.org/docs/attestation/architecture/>.
This is a separate product tier because the hardware, firmware, guest image,
attestation policy, key service, upgrade procedure, and failure recovery must
all be qualified together.

## Supply-chain release boundary

No build command in this repository pushes an image. A reviewed release should:

1. build from a pinned source commit and pinned base-image digests;
2. inspect the loaded image and exported archive locally;
3. run `verify_selfhost_artifact` and secret/private-marker scans;
4. exercise real `seam-client` calls through all four `/v1` routes;
5. create SBOM and provenance attestations with BuildKit's `--sbom` and
   `--provenance` controls:
   <https://docs.docker.com/build/metadata/attestations/>;
6. push only after operator approval to a private registry with per-customer
   read permission; and
7. sign the digest and verify identity/digest claims with Cosign:
   <https://docs.sigstore.dev/cosign/signing/signing_with_containers/> and
   <https://docs.sigstore.dev/cosign/verifying/verify/>.

Build arguments must never carry secrets because provenance can record build
arguments. The image build accepts only the entitlement **public** key. Signing
private keys, API tokens, entitlements, provider credentials, database files,
and registry tokens must never enter the build context.

## Vendor build

Generate an Ed25519 signing key outside the repository and retain the private
key only in the approved signing system. The build receives the public key:

```bash
python -m tools.release.build_selfhost \
  --public-key /approved/path/entitlement-public-key.pem \
  --tag seam-selfhost:local
```

The command uses `docker buildx --load` and deliberately has no push mode.
Issue a customer entitlement without placing the private key in the build:

```bash
python -m tools.release.issue_selfhost_entitlement \
  --private-key /approved/signing/entitlement-private-key.pem \
  --entitlement-id ent_customer_001 \
  --customer-id customer-001 \
  --expires-at 2027-07-27T00:00:00Z \
  --output /approved/customer-001/entitlement.json
```

The issuer refuses to overwrite an existing entitlement. Use
`--private-key-passphrase-file` for an encrypted PEM key; never pass the
passphrase on the command line.

After a local build:

```bash
docker save seam-selfhost:local -o /approved/artifacts/seam-selfhost.tar
python -m tools.release.verify_selfhost_artifact \
  /approved/artifacts/seam-selfhost.tar
```

## Customer one-command operation

Provision these files in an operator-controlled directory:

- `entitlement.json`: vendor-signed entitlement;
- `api-token.txt`: at least 32 random characters, mode `0600`; and
- `operator.env`: copied from `operator.env.example`, with the approved image
  digest or local tag.

Set `SEAM_SELFHOST_ENTITLEMENT_FILE` and `SEAM_SELFHOST_TOKEN_FILE` in
`operator.env` to those absolute paths. The Compose defaults remain convenient
local filenames for an isolated evaluation directory.

Start the service:

```bash
docker compose --env-file selfhost/operator.env \
  -f selfhost/compose.yaml up -d
```

The default mapping is loopback-only (`127.0.0.1:8765`). Keep it that way or
put an authenticated TLS reverse proxy in front. Do not expose the container's
plain HTTP port directly to an untrusted network.

The named `seam-data` volume is persistent but not automatically encrypted.
Place Docker's data root on an encrypted volume or replace the named volume
with a bind mount backed by the customer's LUKS/cloud-encrypted storage.

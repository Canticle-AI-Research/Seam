# seam-runtime compatibility client

`seam-runtime` 2.3.1 is an API-only compatibility package for users upgrading
from the legacy public `seam-runtime` releases. It delegates to the separately
authored Apache-2.0 [`seam-client`](https://pypi.org/project/seam-client/)
package.

It does not contain or start the local SEAM runtime. Remember, recall, and
context commands require access to a separately provisioned SEAM `/v1`
endpoint.

```bash
python -m pip install seam-runtime
export SEAM_SERVER_URL=https://your-seam-server.example.com
export SEAM_API_TOKEN=<api-token>

seam health
seam remember "The user prefers concise answers"
seam recall "answer preferences"
seam context "answer preferences"
```

For new integrations, depend directly on `seam-client`:

```bash
python -m pip install seam-client
```

Public SDK source and issue tracking:
<https://github.com/BlackhatShiftey/Seam_Runtime/tree/main/sdk>

# cedar/ — the leash

Amazon Verified Permissions policy store for Leash, deployed as a nested SAM application
(`Authz` in the root `template.yaml`). It outputs `PolicyStoreId` and `PolicyIdMap`.

| File | What it is |
| --- | --- |
| `schema.json` | Cedar schema, namespace `Leash`. Entity types `Agent` (no attributes), `Instance`, `EcsService`, `AutoScalingGroup` (each `env: String`). Actions `cleanDisk`, `restartService`, `scaleGroup` (context `desiredCapacity: Long`), `terminateInstance`, `deleteResource`. |
| `policies/PermitDevRemediation.cedar` | permit cleanDisk / restartService / scaleGroup when `resource.env == "dev"` |
| `policies/ForbidDestructive.cedar` | forbid terminateInstance and deleteResource for everyone |
| `policies/ForbidProd.cedar` | forbid every action when `resource.env == "prod"` |
| `policies/ForbidScaleAboveCap.cedar` | forbid scaleGroup when `context.desiredCapacity > 4` |
| `template.yaml` | `AWS::VerifiedPermissions::PolicyStore` (STRICT validation, schema inline) + one `AWS::VerifiedPermissions::Policy` per file. |

The policy logical ids in `template.yaml` are the file names, and the inline `Statement` text is
byte-identical to the `.cedar` files. `tests/authz/test_authz_contract.py` enforces both, and also
validates the policies against the schema with cedarpy.

## How the agent uses it

`src/common/authz.py::authorize(action, resource_type, resource_id, resource_env, context)` sends
`IsAuthorized` with principal `Leash::Agent::"leash"`, the resource entity carrying
`{"env": <tag value>}`, and typed context (`{"long": n}`). Verified Permissions returns opaque
policy ids; `POLICY_ID_MAP` (from the `PolicyIdMap` output) translates them back to the names
above so the audit row and the agent's reply say `DENIED by ForbidProd`.

Set `LEASH_LOCAL_AUTHZ=1` to evaluate the same request locally with
[cedarpy](https://pypi.org/project/cedarpy/) against these files instead of calling AWS. That is
what the tests do; it is not used in Lambda.

Cedar semantics that matter: deny by default (no matching `permit` means DENY) and any matching
`forbid` beats every `permit`. A resource without an `env` tag is passed as `env = "unknown"` and
matches no permit.

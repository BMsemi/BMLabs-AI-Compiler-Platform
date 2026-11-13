# Application and compiler architecture

## Access and storage

Django handles identity, projects, organization membership and server-rendered UI. DRF applies the same project visibility rules to resource APIs. Personal projects belong to their owner; organization projects are visible according to current membership and role. Editors can request builds; viewers cannot mutate projects. Superuser operations are separate from ordinary account access.

Uploaded files have opaque private storage paths and recorded names, sizes and SHA-256 hashes. Downloads are authorization-checked. Never expose `private-media` as a static public directory. Media playback endpoints also check access.

## Request, execution and finalization

`builds.services.request_build` validates the selected pipeline and snapshots source/configuration/target metadata. Unsupported or unconfigured work stays blocked. The worker claims queued jobs using a database status transition while holding a single-host process lock.

`builds.runner.execute` dispatches fixed adapters. `compiler.execution.run_command` bounds subprocess time/output, limits inherited environment variables and captures stdout, stderr, exit status and timing. The worker retains reports and partial outputs when an operation fails. Finalization records private artifacts and a manifest; persistence failure cannot leave a successful build status.

States are `blocked`, `queued`, `running`, `succeeded`, `failed` and `cancelled`. Cancellation is checked at stage boundaries. Restart recovery marks interrupted jobs failed/cancelled and recovers available evidence. This is not a distributed queue; optional Celery configuration is not an alternative implemented compiler execution path.

## Adapter boundaries

The Linear adapter accepts a literal model specification parsed with `ast.literal_eval`, imports configured trusted BM/V2 modules in a separate Python runtime, validates integer IR, emits Verilog and generates independent reference vectors. Additional pipelines run logical PE checks, synthesis/equivalence, candidate X2 regression, reference fabric builds or board execution as documented in the README.

Physical execution validates board identity and hash-pinned runtime assets, uses an exclusive board lock and records actual programming/results. The SKY130 adapter uses a different target: it builds fresh snapshots of pinned upstream examples and checks configuration framing. It does not invoke the board loader.

Experimental fabric postprocessor modules remain separate from enabled workflows. The proposed AI agents will coordinate validated operations through a bounded controller; there is no implemented autonomous agent service today.

## Numerical and verification boundaries

Keep the supported model schema, quantization metadata, hardware precision and transfer packing explicit. Synthesis, numerical simulation, formal equivalence, configured-fabric simulation and physical execution are different evidence categories. A pass in one category is not a pass in the others.

Missing tools, source revisions, target configuration or required completion markers must fail or block the relevant operation. Do not substitute cached upstream sample artifacts as newly generated build output.

## Deployment boundaries

The tested desktop deployment uses a single host, loopback origin and Cloudflare Tunnel. The container scaffold provides web/database/cache/reverse-proxy services but no EDA image or compiler worker. Larger deployments require a deliberate worker isolation and scheduling design rather than simply adding web replicas.

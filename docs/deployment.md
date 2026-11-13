# Deployment

## Development

Follow the README quick start with `.env.example`. Use SQLite and console email for local development. Compiler execution is disabled until repositories, tool paths and profiles are configured. The development server is not the production serving process.

## Container scaffold

`compose.yaml` defines PostgreSQL, Redis, the Gunicorn web application and an Nginx TLS reverse proxy. Copy `deploy/production.env.example` to a deployment-specific `.env`, configure secrets and SMTP, and install certificates under the ignored `deploy/certs` directory. Inspect `deploy/nginx.conf` and replace its hostname/certificate configuration for your installation.

The web container runs as a non-root application user. Its EDA tools and BM source dependencies are not installed. Compose does not automatically launch a compiler worker. Configure an appropriate isolated worker separately before enabling compiler execution.

Use `python manage.py migrate`, create an administrator, collect static assets and run `python manage.py check --deploy` under the actual production configuration. Configure PostgreSQL and Redis for multi-process production; the explicit single-host mode is a separate deployment choice.

## Windows origin and Cloudflare Tunnel

`deploy/serve_tunnel.py` starts Waitress on loopback port 18765 and loads the existing BM production hostname/settings. `deploy/run_tunnel.py` supervises the origin, compiler worker and a configured cloudflared connector. Inspect these scripts before adapting them to a different deployment.

Tunnel installation, authentication, DNS and account configuration are external setup tasks. Keep credentials in the operator's private runtime location, not Git. Do not expose the loopback origin or treat a healthy local origin as proof that the public tunnel/DNS works.

The current scripts are specific to the existing Windows deployment. They are published as operational source, not a portable zero-configuration hosting installer. SMTP delivery is independent of the web/tunnel setup and must be tested before inviting users.

## Compiler operation

Configure trusted source/tool paths, run `compiler_inventory`, then start `run_build_worker`. Run only one worker per media directory. Do not restart it during active hardware/build operations without understanding interruption and recovery semantics.

Physical and SKY130 profiles are local, ignored files. Example profiles are intentionally incomplete and physical programming is disabled by default. Restore actual profiles and pinned assets separately during recovery; never reconstruct hardware identity or hashes by guessing.

## Backups and monitoring

Back up the database and private media together. Retain build manifests and the exact tool/source/profile versions needed to interpret results. Protect SMTP, database and tunnel credentials separately. Monitor disk space, worker heartbeat, queue failures, origin health and public HTTPS health.

Public source excludes the live database, uploads, sessions, logs, board runtime and recordings. A fresh checkout starts without production accounts or historical build artifacts. Test recovery in a separate environment before relying on backups.

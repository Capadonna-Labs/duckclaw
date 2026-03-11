# Hybrid Mesh: Arquitectura de Despliegue Distribuido

Arquitectura que combina **Tailscale** (mesh interno) y **Cloudflare Tunnel** (acceso público) para el DuckClaw API Gateway en Mac Mini.

## Diagrama de flujo

```
┌─────────────────────────────────────────────────────────────────┐
│                        Mac Mini M4                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │ DuckClaw-Gateway │  │ Cloudflare-Tunnel│  │ MLX Inference│  │
│  │     :8000        │  │                  │  │    :8080    │  │
│  └────────┬─────────┘  └────────┬─────────┘  └──────┬───────┘  │
│           │                     │                    │          │
│           └─────────────────────┼────────────────────┘          │
│                                 │                               │
│                         ┌───────▼───────┐                       │
│                         │    DuckDB     │                       │
│                         └───────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
           ▲                                    ▲
           │ X-Tailscale-Auth-Key                │ HTTPS (Cloudflare)
           │ (100.x.y.z)                         │
    ┌──────┴──────┐                     ┌──────┴──────┐
    │ Tailscale   │                     │  Cloudflare  │
    │ Mesh        │                     │  Public      │
    └──────┬──────┘                     └──────┬──────┘
           │                                    │
    ┌──────┴──────┐                     ┌──────┴──────┐
    │ n8n (VPS)   │                     │ Angular /   │
    │ IBKR Gateway│                     │ clientes    │
    └─────────────┘                     └─────────────┘
```

## Requisitos previos

- **Tailscale** instalado en Mac Mini y VPS
- **Cloudflare Zero Trust**: túnel `duckclaw-api` configurado en Cloudflare Dashboard
- **cloudflared** instalado en Mac Mini (`brew install cloudflared`)
- **PM2** (`npm install -g pm2`)

## Variables de entorno

Crear o editar `.env` en la raíz del proyecto:

```bash
JWT_SECRET=<secret-para-firmar-JWT>
DUCKCLAW_TAILSCALE_AUTH_KEY=<clave-para-n8n-via-tailscale>
DUCKCLAW_MODE=local

# IBKR portfolio vía Tailscale (Capadonna Observability API en VPS)
IBKR_PORTFOLIO_API_URL=http://100.97.151.69:8002/api/portfolio/summary
IBKR_PORTFOLIO_API_KEY=<shared_secret_o_vacío_si_la_API_no_exige_auth>
```

**IBKR:** El skill `get_ibkr_portfolio` consulta el contexto de la cuenta IBKR en el VPS. Requiere que la Capadonna Observability API esté corriendo en el VPS (ver sección siguiente).

### Flujo IBKR vía Tailscale

```
Mac Mini (DuckClaw-Gateway)  --Tailscale-->  VPS (Capadonna Observability API :8001)
       │                                              │
       │ get_ibkr_portfolio skill                      │ get_account_snapshot()
       │ IBKR_PORTFOLIO_API_URL                        │ → TWS 127.0.0.1:7497
       └──────────────────────────────────────────────┘
```

1. En el VPS, instalar el servicio `capadonna-observability` (ver `scripts/capadonna-observability.service`).
2. La API expone `/api/portfolio/summary` y `/api/positions`.
3. El DuckClaw-Gateway en Mac Mini usa `IBKR_PORTFOLIO_API_URL` para alcanzar el VPS por Tailscale.

## Despliegue con PM2

1. **Inferencia MLX** (si se usa localmente):

   ```bash
   pm2 start ecosystem.config.cjs
   ```

2. **Gateway + Cloudflare Tunnel**:

   ```bash
   pm2 start ecosystem.hybrid.config.cjs
   pm2 save
   ```

   Esto levanta:
   - **DuckClaw-Gateway**: API en `0.0.0.0:8000`
   - **Cloudflare-Tunnel**: expone el gateway vía Cloudflare

3. **Comandos útiles**:

   ```bash
   pm2 logs                    # Ver logs de todos los procesos
   pm2 logs DuckClaw-Gateway   # Solo gateway
   pm2 restart DuckClaw-Gateway
   pm2 stop DuckClaw-Gateway Cloudflare-Tunnel
   ```

## Configuración de Cloudflare Zero Trust

1. En [Cloudflare Zero Trust](https://one.dash.cloudflare.com/), ir a **Networks** → **Tunnels**
2. Crear o editar el túnel `duckclaw-api`
3. Añadir un **Public Hostname** que apunte al puerto 8000 del Mac Mini
4. Autenticar `cloudflared` en el Mac Mini:

   ```bash
   cloudflared tunnel login
   cloudflared tunnel run duckclaw-api  # o usar PM2
   ```

## Capadonna Observability API (VPS)

Para que el skill `get_ibkr_portfolio` funcione, la Capadonna Observability API debe estar corriendo en el VPS:

```bash
# Copiar el service desde DuckClaw (Mac Mini) al VPS
scp scripts/capadonna-observability.service capadonna@<VPS_IP>:/tmp/

# En el VPS
sudo cp /tmp/capadonna-observability.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable capadonna-observability
sudo systemctl start capadonna-observability
```

La API escucha en `0.0.0.0:8002`. **Paper vs Live:** TWS usa puerto 7497 (paper) y 7496 (live). En `capadonna-observability.service` usa `IB_ENV=live` para cuenta real (cash, posiciones) o `IB_ENV=paper` para simulada. La Mac Mini la alcanza por Tailscale (`100.97.151.69:8002`).

**Dependencias:** Si el servicio falla con `ModuleNotFoundError`, instalar en el venv de Capadonna-Driller:
```bash
cd /home/capadonna/projects/Capadonna-Driller
uv pip install --python .venv/bin/python pydantic-core pydantic anyio annotated-types click
```

## Firewall

En Mac Mini, el tráfico por Tailscale debe poder alcanzar el puerto 8000. Ver `scripts/firewall_mac_mini.sh` para instrucciones.

```bash
./scripts/firewall_mac_mini.sh
```

## Rutas API

| Ruta | Descripción |
|------|-------------|
| `/api/v1/agent/chat` | **Recomendado para n8n/Telegram.** Worker dinámico vía `/role`. Default: finanz. |
| `/api/v1/agent/{worker_id}/chat` | Legacy (worker fijo en URL) |
| `/api/v1/t/{tenant_id}/agent/{worker_id}/chat` | Con tenant (namespacing futuro) |
| `/api/v1/agent/{worker_id}/history` | Historial legacy |
| `/api/v1/t/{tenant_id}/agent/{worker_id}/history` | Historial con tenant |

**Autenticación:**
- **Tailscale** (interno): header `X-Tailscale-Auth-Key` → `source_type: INTERNAL_TRUSTED`
- **JWT** (público): header `Authorization: Bearer <token>` → `source_type: PUBLIC_EXTERNAL`

## Audit

Cada petición registra: `user_id`, `worker_id`, `tenant_id`, `endpoint`, `source_ip`, `source_type` (INTERNAL_TRUSTED / PUBLIC_EXTERNAL), `timestamp`, `elapsed_ms`, `status_code`.

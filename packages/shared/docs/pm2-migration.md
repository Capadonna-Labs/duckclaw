# PM2: motor de inferencia MLX para DuckClaw

## Arrancar el inference engine (MLX) con PM2

Desde la raíz del repo:

```bash
cd /ruta/al/repo/duckclaw
pm2 start ecosystem.config.cjs
pm2 save
```

Esto levanta **DuckClaw-Inference**, que ejecuta `mlx/start_mlx.sh` (servidor MLX OpenAI-compatible en el puerto 8080). DuckClaw usa por defecto `http://127.0.0.1:8080/v1` cuando `provider=mlx`.

- **Logs:** `pm2 logs DuckClaw-Inference`
- **Parar:** `pm2 stop DuckClaw-Inference`
- **Reiniciar:** `pm2 restart DuckClaw-Inference`

Configuración en `.env` (opcional): `MLX_PYTHON`, `MLX_MODEL_PATH`, `MLX_PORT`.

## Procesos antiguos (Minecraft-Engine, Inference-Engine, etc.)

Si en `pm2 list` ves procesos que no quieres (p. ej. **Minecraft-Engine** o un **Inference-Engine** antiguo), están persistidos en `~/.pm2/dump.pm2`. Para usar solo **DuckClaw-Inference**:

1. `pm2 stop <nombre> && pm2 delete <nombre>`
2. `pm2 start ecosystem.config.cjs`
3. `pm2 save`

Resumen: **delete old → start new → save**.

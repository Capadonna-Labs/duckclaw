# PM2: por qué reaparece Minecraft-Engine y migración a Inference-Engine

## Causa

El proceso **Minecraft-Engine** que ves en `pm2 list` no viene del repo DuckClaw. Está persistido en la configuración de PM2 del usuario (`~/.pm2/dump.pm2`). PM2 guarda ahí todos los procesos que has arrancado y los vuelve a cargar al reiniciar PM2 o al abrir una nueva terminal donde se ejecuta `pm2 resurrect` (o el arranque por defecto).

- **Minecraft-Engine** en tu máquina: definido fuera del repo (p. ej. con `pm2 start /Users/.../Desktop/start_mlx.sh --name Minecraft-Engine`). Su definición está en `~/.pm2/dump.pm2`.
- **Inference-Engine**: es el nombre definido en este repo en `ecosystem.config.cjs`. Si solo haces `pm2 start ecosystem.config.cjs` desde el repo, se crea **Inference-Engine**, pero el proceso antiguo **Minecraft-Engine** sigue existiendo en la lista porque fue añadido en otro momento y quedó guardado.

Por eso "sale otra vez" Minecraft-Engine: PM2 está mostrando lo que tiene persistido, no solo lo que arrancas desde `ecosystem.config.cjs`.

## Migración a Inference-Engine

Si quieres usar solo **Inference-Engine** (el del repo) y dejar de tener **Minecraft-Engine**:

1. **Parar y eliminar el proceso antiguo** (opcional: guarda la salida de `pm2 describe Minecraft-Engine` si quieres replicar algo después):
   ```bash
   pm2 stop Minecraft-Engine
   pm2 delete Minecraft-Engine
   ```

2. **Arrancar con la config del repo** (desde la raíz del repo DuckClaw):
   ```bash
   cd /ruta/al/repo/duckclaw
   pm2 start ecosystem.config.cjs
   ```

3. **Persistir la nueva lista** para que al reiniciar PM2 no vuelva a cargar Minecraft-Engine:
   ```bash
   pm2 save
   ```

Resumen: **delete old → start new → save**.

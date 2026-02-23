/**
 * PM2 config for MLX inference server (OpenAI-compatible).
 * Start: pm2 start ecosystem.config.cjs
 * Stop:  pm2 stop Inference-Engine
 */
module.exports = {
  apps: [
    {
      name: "Inference-Engine",
      script: "python",
      args: "-m mlx_lm server --model /Users/juanjosearevalocamargo/Desktop/models/Slayer-8B-V1.1 --port 8000",
      cwd: process.env.HOME || "/",
      interpreter: "none",
      autorestart: true,
      watch: false,
      max_restarts: 10,
      env: {},
    },
  ],
};

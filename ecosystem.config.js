module.exports = {
  apps: [
    {
      name: "haewon-bot",
      script: "bot.py",
      interpreter: "python3",
      cwd: __dirname,
      restart_delay: 3000,
      max_restarts: 10,
      env_file: ".env",
    },
    {
      name: "haewon-web",
      script: "web_panel.py",
      interpreter: "python3",
      cwd: __dirname,
      restart_delay: 3000,
      max_restarts: 10,
      env_file: ".env",
    },
  ],
};

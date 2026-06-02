module.exports = {
  apps: [
    {
      name: "pointbot",
      script: "bot.py",
      interpreter: "python3",
      watch: false,
      autorestart: true,
      restart_delay: 3000,
      env: { PYTHONUNBUFFERED: "1" },
    },
    {
      name: "pointweb",
      script: "web.py",
      interpreter: "python3",
      watch: false,
      autorestart: true,
      restart_delay: 3000,
      env: { PYTHONUNBUFFERED: "1" },
    },
    {
      name: "baccaratbot",
      script: "baccarat/bot.py",
      interpreter: "python3",
      watch: false,
      autorestart: true,
      restart_delay: 3000,
      env: { PYTHONUNBUFFERED: "1" },
    },
  ],
};
